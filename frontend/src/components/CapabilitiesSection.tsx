import React from 'react';
import {
  IconSparkles,
  IconClock,
  IconWallet,
  IconRefresh,
  IconNavigation,
  IconActivity,
  IconShield,
} from './Icons';

interface CapabilitiesSectionProps {
  onStartPlanning: () => void;
}

export const CapabilitiesSection: React.FC<CapabilitiesSectionProps> = ({ onStartPlanning }) => {
  const capabilities = [
    {
      icon: <IconSparkles size={20} className="cap-icon-coral" />,
      tag: 'PARSING',
      title: 'Implicit Context Extraction',
      description:
        'Plain text intention becomes structured reality. Dayform parses dates, time-of-day, group sizes, and budget constraints without making you click through dropdown forms.',
    },
    {
      icon: <IconClock size={20} className="cap-icon-coral" />,
      tag: 'SEQUENCING',
      title: 'Temporal & Spatial Logic',
      description:
        'Stops aren’t just recommended—they are sequenced logically. Dayform checks travel buffers, realistic stop durations, and verified operating hours so you never face a locked door.',
    },
    {
      icon: <IconRefresh size={20} className="cap-icon-coral" />,
      tag: 'ADAPTIVE',
      title: 'Conversational Replanning',
      description:
        'Life changes. Running 45 minutes late? Need a cheaper alternative? Tell Dayform conversationally and the engine recalibrates your plan while keeping intact stops preserved.',
    },
    {
      icon: <IconWallet size={20} className="cap-icon-coral" />,
      tag: 'BUDGETS',
      title: 'Deterministic Budget Tracking',
      description:
        'Never get surprised by the bill. Dayform tallies real venue price levels and tracks remaining headroom against your strict ceiling, showing transparent per-person breakdowns.',
    },
    {
      icon: <IconNavigation size={20} className="cap-icon-coral" />,
      tag: 'EXECUTION',
      title: 'Real-World Execution',
      description:
        'One tap opens directions in Google Maps, initiates direct phone calls, or opens venue websites. Check off stops as you complete them to keep your active day organized.',
    },
    {
      icon: <IconActivity size={20} className="cap-icon-coral" />,
      tag: 'MONITORING',
      title: 'Live Intelligence & Health',
      description:
        'Continuous checks confirm venue operating status and schedule validity. If a venue unexpectedly closes or schedule conflicts arise, Dayform flags the change and proposes a smooth adaptation.',
    },
  ];

  return (
    <section id="capabilities" className="capabilities-section">
      <div className="capabilities-container">
        {/* Header */}
        <div className="capabilities-header">
          <div className="section-eyebrow">
            <IconShield size={14} className="eyebrow-icon" />
            <span>PLANNING INTELLIGENCE</span>
          </div>
          <h2 className="capabilities-heading">
            Built for how days
            <br />
            <span className="serif-italic-accent">actually happen.</span>
          </h2>
          <p className="capabilities-subheading">
            Search engines give you ten thousand links. Dayform gives you one coherent, verified plan.
          </p>
        </div>

        {/* Feature Grid */}
        <div className="capabilities-grid">
          {capabilities.map((cap, i) => (
            <div key={i} className="capability-card">
              <div className="cap-top-row">
                <div className="cap-icon-wrapper">{cap.icon}</div>
                <span className="cap-tag">{cap.tag}</span>
              </div>
              <h3 className="cap-title">{cap.title}</h3>
              <p className="cap-desc">{cap.description}</p>
            </div>
          ))}
        </div>

        {/* Bottom Banner */}
        <div className="capabilities-bottom-banner">
          <div className="banner-text">
            <h3 className="banner-title">Experience intelligent planning today.</h3>
            <p className="banner-desc">Describe any outing, celebration, or weekend plan in plain language.</p>
          </div>
          <button
            type="button"
            className="banner-cta-button"
            onClick={onStartPlanning}
          >
            <span>Plan an intention</span>
            <span className="banner-arrow">→</span>
          </button>
        </div>
      </div>
    </section>
  );
};
