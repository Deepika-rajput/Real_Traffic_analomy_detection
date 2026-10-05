import torch
import torch.nn as nn
from torchvision.models import resnet18, ResNet18_Weights

from .config import CLASSES, CLIP_LEN, CNN_DIM, MOTION_DIM


class FrameEncoder(nn.Module):
    """Frozen ImageNet ResNet18 -> one 512-d appearance vector per frame (spatial features).

    Input : (N, 3, H, W) RGB, float in [0, 1]   (ImageNet normalisation is done here)
    Output: (N, 512)
    """

    def __init__(self):
        super().__init__()
        cnn = resnet18(weights=ResNet18_Weights.DEFAULT)
        cnn.fc = nn.Identity()
        self.cnn = cnn
        for p in self.cnn.parameters():
            p.requires_grad = False
        self.register_buffer("mean", torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1))
        self.register_buffer("std", torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1))
        self.eval()

    def train(self, mode: bool = True):
        return super().train(False)          # BatchNorm stays frozen

    @torch.no_grad()
    def forward(self, x):
        return self.cnn((x - self.mean) / self.std)


class TemporalTransformer(nn.Module):
    """Transformer over a sequence of per-frame features (temporal modelling).

    Input : (B, T, 512 + 15)  = ResNet appearance + optical-flow motion summary
    Output: (B, len(CLASSES)) logits, order = config.CLASSES

    Appearance and motion get separate projections that are summed. The motion branch
    deliberately has NO LayerNorm: absolute motion level (flowing vs stopped) is the signal.
    ~0.3M params -> trains in minutes on CPU once features are cached.
    """

    def __init__(self, d_model=128, nhead=4, layers=2, ff=256, dropout=0.2,
                 clip_len=CLIP_LEN, num_classes=len(CLASSES)):
        super().__init__()
        self.proj_cnn = nn.Sequential(nn.LayerNorm(CNN_DIM), nn.Linear(CNN_DIM, d_model))
        self.proj_motion = nn.Sequential(nn.Linear(MOTION_DIM, 32), nn.GELU(), nn.Linear(32, d_model))
        self.cls = nn.Parameter(torch.zeros(1, 1, d_model))
        self.pos = nn.Parameter(torch.zeros(1, clip_len + 1, d_model))   # learned positions (+CLS)
        nn.init.trunc_normal_(self.cls, std=0.02)
        nn.init.trunc_normal_(self.pos, std=0.02)

        layer = nn.TransformerEncoderLayer(
            d_model=d_model, nhead=nhead, dim_feedforward=ff,
            dropout=dropout, batch_first=True, norm_first=True,
        )
        self.encoder = nn.TransformerEncoder(layer, num_layers=layers, enable_nested_tensor=False)
        self.norm = nn.LayerNorm(d_model)
        self.head = nn.Linear(d_model, num_classes)

    def forward(self, feats):
        x = self.proj_cnn(feats[..., :CNN_DIM]) + self.proj_motion(feats[..., CNN_DIM:])
        cls = self.cls.expand(x.size(0), -1, -1)
        x = torch.cat([cls, x], dim=1) + self.pos[:, : x.size(1) + 1]
        x = self.encoder(x)
        return self.head(self.norm(x[:, 0]))                   # CLS token -> logits


class AccidentTransformer(nn.Module):
    """CNN (spatial) + Transformer (temporal).

    Training : features are cached once (extract_features.py); only `temporal` is trained.
    Inference: `encoder` runs ONCE per sampled frame, features go in a ring buffer,
               `temporal` runs on the last CLIP_LEN of them.
    """

    def __init__(self):
        super().__init__()
        self.encoder = FrameEncoder()
        self.temporal = TemporalTransformer()

    def encode(self, frames):                 # (N,3,H,W) -> (N,512)
        return self.encoder(frames)

    def forward(self, feats):                 # (B,T,527) -> (B,num_classes)
        return self.temporal(feats)
