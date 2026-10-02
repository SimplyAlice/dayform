import React, { useState, useEffect } from 'react';
import { IconArrowRight, IconPlus, IconMenu, IconX } from './Icons';

interface NavigationProps {
  hasActivePlan: boolean;
  isPlanning: boolean;
  onNewPlan: () => void;
  onFocusInput: () => void;
  viewMode: 'landing' | 'workspace' | 'library';
  onSwitchView?: (mode: 'landing' | 'workspace' | 'library') => void;
}

export const Navigation: React.FC<NavigationProps> = ({
  hasActivePlan,
  isPlanning,
  onNewPlan,
  onFocusInput,
  viewMode,
  onSwitchView,
}) => {
  const [isScrolled, setIsScrolled] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  useEffect(() => {
    const handleScroll = () => {
      setIsScrolled(window.scrollY > 30);
    };

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && mobileMenuOpen) {
        setMobileMenuOpen(false);
      }
    };

    window.addEventListener('scroll', handleScroll, { passive: true });
    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('scroll', handleScroll);
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [mobileMenuOpen]);

  useEffect(() => {
    if (mobileMenuOpen) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => {
      document.body.style.overflow = '';
    };
  }, [mobileMenuOpen]);

  const handleLinkClick = (anchorId: string) => {
    setMobileMenuOpen(false);
    if ((viewMode === 'workspace' || viewMode === 'library') && onSwitchView) {
      onSwitchView('landing');
      setTimeout(() => {
        const elem = document.getElementById(anchorId);
        elem?.scrollIntoView({ behavior: 'smooth' });
      }, 100);
      return;
    }

    const elem = document.getElementById(anchorId);
    elem?.scrollIntoView({ behavior: 'smooth' });
  };

  const handlePlanClick = () => {
    setMobileMenuOpen(false);
    if (viewMode === 'workspace') {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } else if (viewMode === 'library' && onSwitchView) {
      onSwitchView('landing');
      setTimeout(() => onFocusInput(), 100);
    } else {
      onFocusInput();
    }
  };

  const handleBrandClick = () => {
    setMobileMenuOpen(false);
    if (hasActivePlan) {
      if (onSwitchView) {
        onSwitchView('landing');
      } else {
        onNewPlan();
      }
    } else {
      if (viewMode !== 'landing' && onSwitchView) {
        onSwitchView('landing');
      }
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  };

  return (
    <>
      <header className={`product-nav ${isScrolled ? 'scrolled' : 'at-top'}`}>
        <div className="nav-container">
          {/* Brand Mark */}
          <div
            className="brand-group"
            onClick={handleBrandClick}
            role="button"
            tabIndex={0}
            aria-label="Dayform Homepage"
          >
            <span className="brand-mark">DAYFORM</span>
            <span className="brand-badge">Real-World Planning</span>
          </div>

          {/* Desktop Nav Links */}
          <nav className="nav-links-desktop" aria-label="Main Navigation">
            <button
              type="button"
              className={`nav-link-item ${viewMode === 'landing' ? 'active' : ''}`}
              onClick={handlePlanClick}
            >
              Plan
            </button>
            <button
              type="button"
              className="nav-link-item"
              onClick={() => handleLinkClick('how-it-works')}
            >
              How it works
            </button>
            <button
              type="button"
              className="nav-link-item"
              onClick={() => handleLinkClick('capabilities')}
            >
              Capabilities
            </button>
            <button
              type="button"
              className={`nav-link-item ${viewMode === 'library' ? 'active' : ''}`}
              onClick={() => {
                setMobileMenuOpen(false);
                onSwitchView?.('library');
              }}
            >
              Plan Library
            </button>
            {hasActivePlan && (
              <button
                type="button"
                className="nav-link-item active-plan-link"
                onClick={() => onSwitchView?.('workspace')}
              >
                <span className="active-plan-dot" />
                <span>Active Plan</span>
              </button>
            )}
          </nav>

          {/* Right Action Cluster */}
          <div className="nav-right">
            {viewMode === 'landing' && (
              <div className="nav-status-indicator" title="Connected to Dayform Planning Engine">
                <span className="live-status-dot" />
                <span className="live-status-label">Engine ready</span>
              </div>
            )}

            {hasActivePlan ? (
              <button
                type="button"
                className="nav-action-button new-plan"
                onClick={onNewPlan}
                disabled={isPlanning}
              >
                <IconPlus size={14} />
                <span>New plan</span>
              </button>
            ) : (
              <button
                type="button"
                className="nav-action-button start-plan"
                onClick={onFocusInput}
              >
                <span>Plan it</span>
                <IconArrowRight size={14} className="nav-btn-arrow" />
              </button>
            )}

            {/* Mobile Hamburger Button */}
            <button
              type="button"
              className="mobile-menu-toggle"
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              aria-label={mobileMenuOpen ? 'Close navigation menu' : 'Open navigation menu'}
              aria-expanded={mobileMenuOpen}
            >
              {mobileMenuOpen ? <IconX size={20} /> : <IconMenu size={20} />}
            </button>
          </div>
        </div>
      </header>

      {/* Mobile Drawer Overlay */}
      {mobileMenuOpen && (
        <div className="mobile-nav-overlay" onClick={() => setMobileMenuOpen(false)}>
          <div className="mobile-nav-sheet" onClick={(e) => e.stopPropagation()}>
            <div className="mobile-nav-header">
              <div className="brand-group" onClick={handleBrandClick}>
                <span className="brand-mark">DAYFORM</span>
                <span className="brand-badge">Real-World Planning</span>
              </div>
              <button
                type="button"
                className="mobile-close-btn"
                onClick={() => setMobileMenuOpen(false)}
                aria-label="Close menu"
              >
                <IconX size={20} />
              </button>
            </div>

            <div className="mobile-nav-links">
              <button
                type="button"
                className="mobile-nav-item"
                onClick={handlePlanClick}
              >
                <span>Plan an intention</span>
                <IconArrowRight size={16} />
              </button>
              <button
                type="button"
                className="mobile-nav-item"
                onClick={() => handleLinkClick('how-it-works')}
              >
                <span>How it works</span>
                <IconArrowRight size={16} />
              </button>
              <button
                type="button"
                className="mobile-nav-item"
                onClick={() => handleLinkClick('capabilities')}
              >
                <span>Capabilities</span>
                <IconArrowRight size={16} />
              </button>
              <button
                type="button"
                className="mobile-nav-item"
                onClick={() => {
                  setMobileMenuOpen(false);
                  onSwitchView?.('library');
                }}
              >
                <span>Plan Library</span>
                <IconArrowRight size={16} />
              </button>
              {hasActivePlan && (
                <button
                  type="button"
                  className="mobile-nav-item highlight"
                  onClick={() => {
                    setMobileMenuOpen(false);
                    onSwitchView?.('workspace');
                  }}
                >
                  <span>Return to active plan</span>
                  <IconArrowRight size={16} />
                </button>
              )}
            </div>

            <div className="mobile-nav-footer">
              <div className="mobile-engine-status">
                <span className="live-status-dot" />
                <span>Live intelligence active</span>
              </div>
              {hasActivePlan ? (
                <button
                  type="button"
                  className="mobile-cta-btn"
                  onClick={() => {
                    setMobileMenuOpen(false);
                    onNewPlan();
                  }}
                >
                  <IconPlus size={16} />
                  <span>Start new plan</span>
                </button>
              ) : (
                <button
                  type="button"
                  className="mobile-cta-btn"
                  onClick={handlePlanClick}
                >
                  <span>Start planning now</span>
                  <IconArrowRight size={16} />
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
};
