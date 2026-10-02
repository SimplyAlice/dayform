import React from 'react';

interface FooterProps {
  onStartPlanning?: () => void;
  onOpenLibrary?: () => void;
}

export const Footer: React.FC<FooterProps> = ({ onStartPlanning, onOpenLibrary }) => {
  return (
    <footer className="editorial-footer">
      <div className="footer-container">
        <div className="footer-top-row">
          <div className="footer-brand-col">
            <span className="footer-logo">DAYFORM</span>
            <p className="footer-tagline">
              Intelligent real-world planning. Give shape to your day.
            </p>
          </div>

          <div className="footer-links-col">
            <span className="footer-col-title">Navigation</span>
            {onStartPlanning && (
              <button type="button" className="footer-link" onClick={onStartPlanning}>
                Plan an intention
              </button>
            )}
            <a href="#how-it-works" className="footer-link">
              How it works
            </a>
            <a href="#capabilities" className="footer-link">
              Capabilities
            </a>
            {onOpenLibrary && (
              <button type="button" className="footer-link" onClick={onOpenLibrary}>
                Saved Plans
              </button>
            )}
          </div>

          <div className="footer-links-col">
            <span className="footer-col-title">Engine</span>
            <span className="footer-meta-item">Version 0.1.0</span>
            <span className="footer-meta-item">Adaptive Sequencing</span>
            <span className="footer-meta-item">Live Intelligence Active</span>
          </div>
        </div>

        <div className="footer-bottom-row">
          <span className="footer-copy">© 2026 Dayform. Built with verified places and real-world logic.</span>
          <div className="footer-system-status">
            <span className="live-status-dot" />
            <span>All services operational</span>
          </div>
        </div>
      </div>
    </footer>
  );
};
