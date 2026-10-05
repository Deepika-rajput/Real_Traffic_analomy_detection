import React from 'react';
import { LABELS, STATE_TONE, STATUS } from '../util.js';

export const Badge = ({ tone = 'gray', children, title }) => (
  <span className={`badge ${tone}`} title={title}>{children}</span>
);

export const LabelBadge = ({ label }) => {
  const m = LABELS[label] || { name: label, tone: 'gray' };
  return <Badge tone={m.tone}>{m.name}</Badge>;
};

export const StatusBadge = ({ status }) => {
  const m = STATUS[status] || { name: status, tone: 'gray' };
  return <Badge tone={m.tone}>{m.name}</Badge>;
};

export const SeverityBadge = ({ severity }) => (
  <Badge tone={severity === 'high' ? 'red' : severity === 'medium' ? 'orange' : 'gray'} title="from peak model probability">
    {severity}
  </Badge>
);

export const StateBadge = ({ state }) => (
  <Badge tone={STATE_TONE[state] || 'gray'}>{(state || '').replace('_', ' ')}</Badge>
);

export const ErrorBox = ({ error, onClose }) =>
  error ? (
    <div className="alertbox error" role="alert">
      <span>{String(error.message || error)}</span>
      {onClose && <button className="link" onClick={onClose}>dismiss</button>}
    </div>
  ) : null;

export const Empty = ({ children }) => <div className="empty">{children}</div>;

export function Modal({ title, onClose, children, wide }) {
  return (
    <div className="modal-back" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${wide ? 'wide' : ''}`} role="dialog" aria-label={title}>
        <div className="modal-head">
          <h3>{title}</h3>
          <button className="icon" onClick={onClose} aria-label="close">✕</button>
        </div>
        {children}
      </div>
    </div>
  );
}

export const Card = ({ title, actions, children, className = '' }) => (
  <section className={`card ${className}`}>
    {(title || actions) && (
      <div className="card-head">
        <h2>{title}</h2>
        <div className="row">{actions}</div>
      </div>
    )}
    {children}
  </section>
);
