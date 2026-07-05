/**
 * Modal — generic accessible modal dialog.
 *
 * Features:
 * - Focus trap (first focusable element on open)
 * - Closes on Escape key
 * - Backdrop click closes (unless `disableBackdropClose`)
 * - Portal rendered to document.body via React Portal
 */
import { useEffect, useRef, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  disableBackdropClose?: boolean;
}

export function Modal({ open, onClose, title, children, disableBackdropClose }: ModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null);

  // Escape key handler
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open, onClose]);

  // Focus management: move focus into dialog when it opens
  useEffect(() => {
    if (!open || !dialogRef.current) return;
    const focusable = dialogRef.current.querySelectorAll<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );
    focusable[0]?.focus();
  }, [open]);

  if (!open) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="modal-title"
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/70 backdrop-blur-sm"
        onClick={disableBackdropClose ? undefined : onClose}
        aria-hidden="true"
      />

      {/* Panel */}
      <div
        ref={dialogRef}
        className="relative z-10 w-full max-w-sm bg-gray-900 border border-gray-700 rounded-2xl p-6 shadow-2xl"
      >
        <h2 id="modal-title" className="text-base font-semibold text-gray-100 mb-4">
          {title}
        </h2>
        {children}
      </div>
    </div>,
    document.body
  );
}
