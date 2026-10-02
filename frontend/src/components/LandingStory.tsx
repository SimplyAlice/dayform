import React, { useState, useEffect, useRef } from 'react';
import {
  IconArrowRight,
  IconCalendar,
  IconMapPin,
  IconUsers,
  IconWallet,
  IconCheckCircle,
  IconCheck,
  IconSparkles,
  IconNavigation,
  IconPhone,
  IconUtensils,
  IconPalette,
} from './Icons';

interface LandingStoryProps {
  onStartPlanning: (initialPrompt?: string) => void;
}

interface StoryChapter {
  id: string;
  stepNumber: string;
  tag: string;
  title: string;
  lead: string;
  body: string;
  keyTakeaway: string;
}

const CHAPTERS: StoryChapter[] = [
  {
    id: 'scene-intent',
    stepNumber: '01',
    tag: 'THE INTENTION',
    title: 'Speak human. Not search queries.',
    lead: 'Real plans don’t start with coordinates, filters, or fifteen open browser tabs.',
    body: 'They start with a simple impulse: dinner with five friends on a Saturday night, a romantic evening under R800, or a spontaneous cultural afternoon. Dayform takes your plain-spoken intent as the authoritative starting point.',
    keyTakeaway: 'No drop-downs. No date pickers. Just describe what you want.',
  },
  {
    id: 'scene-understand',
    stepNumber: '02',
    tag: 'UNDERSTANDING',
    title: 'From messy thoughts to structured context.',
    lead: 'Dayform immediately extracts the implicit geometry of your day.',
    body: 'The engine parses temporal bounds, geographic center points, party sizes, and financial ceilings—without asking you to fill out forms. It forms an authoritative brief before searching for a single place.',
    keyTakeaway: 'Structured temporal and financial boundaries locked in milliseconds.',
  },
  {
    id: 'scene-evaluate',
    stepNumber: '03',
    tag: 'INTELLIGENCE',
    title: 'Evaluating places, verified hours, and real trade-offs.',
    lead: 'A list of places isn’t a plan. Venues must make sense together.',
    body: 'Dayform scans local options, checks real operating schedules to prevent arriving at closed doors, calculates physical transit buffers, and filters candidates so the combined cost stays strictly within your budget limit.',
    keyTakeaway: 'Verified opening hours and geographic clusters, checked before proposing.',
  },
  {
    id: 'scene-plan',
    stepNumber: '04',
    tag: 'THE ITINERARY',
    title: 'A coherent sequence. Not an isolated list.',
    lead: 'You didn’t search for all of this. Dayform put it together.',
    body: 'The engine sequences stops into a realistic flow with calculated start times, duration buffers, and transparent cost rollups. Every venue has a clear purpose in the sequence, from kickoff to wind-down.',
    keyTakeaway: 'Timed, paced, and budget-verified. Ready to preview or tweak.',
  },
  {
    id: 'scene-adapt',
    stepNumber: '05',
    tag: 'ADAPTATION',
    title: 'Things change. Your plan adapts instantly.',
    lead: 'Real life doesn’t follow a static spreadsheet.',
    body: 'Running 45 minutes late? Rain clouds moving in? Friends want coffee instead of dessert? Tell Dayform conversationally. The engine calculates the minimal diff, shifts downstream times, and prevents schedule collapse.',
    keyTakeaway: 'Dynamic recalculation with minimal disruption to your day.',
  },
  {
    id: 'scene-execute',
    stepNumber: '06',
    tag: 'EXECUTION',
    title: 'Direct action in the real world.',
    lead: 'From decision to reality in a single tap.',
    body: 'Every confirmed stop includes one-tap directions in Google Maps, direct venue contacts, and live schedule health monitoring. When things shift on the ground, Dayform highlights proposed adjustments.',
    keyTakeaway: 'Directions in Google Maps, live schedule monitoring, and instant tweaks.',
  },
];

export const LandingStory: React.FC<LandingStoryProps> = ({ onStartPlanning }) => {
  const [activeStep, setActiveStep] = useState(0);
  const chapterRefs = useRef<(HTMLDivElement | null)[]>([]);

  useEffect(() => {
    const handleScrollObserver = () => {
      const viewportHeight = window.innerHeight;
      const triggerPoint = viewportHeight * 0.45;

      let currentActive = 0;
      let minDistance = Infinity;

      chapterRefs.current.forEach((el, index) => {
        if (!el) return;
        const rect = el.getBoundingClientRect();
        const elCenter = rect.top + rect.height / 2;
        const dist = Math.abs(elCenter - triggerPoint);
        if (rect.top <= triggerPoint && rect.bottom >= triggerPoint) {
          currentActive = index;
          minDistance = -1;
        } else if (minDistance !== -1 && dist < minDistance) {
          minDistance = dist;
          currentActive = index;
        }
      });

      setActiveStep(currentActive);
    };

    window.addEventListener('scroll', handleScrollObserver, { passive: true });
    handleScrollObserver(); // Initial check

    return () => window.removeEventListener('scroll', handleScrollObserver);
  }, []);

  const scrollToChapter = (index: number) => {
    setActiveStep(index);
    const target = chapterRefs.current[index];
    if (target) {
      const navOffset = 90;
      const elementPosition = target.getBoundingClientRect().top + window.scrollY;
      window.scrollTo({
        top: elementPosition - navOffset,
        behavior: 'smooth',
      });
    }
  };

  return (
    <section id="how-it-works" className="story-section">
      {/* Story Section Header */}
      <div className="story-intro-container">
        <div className="story-eyebrow">
          <IconSparkles size={14} className="eyebrow-icon" />
          <span>HOW IT WORKS</span>
        </div>
        <h2 className="story-main-heading">
          From raw human thought
          <br />
          <span className="serif-italic-accent">to verified reality.</span>
        </h2>
        <p className="story-intro-lead">
          Traditional travel and booking apps expect you to do all the heavy lifting: search 20 places,
          check each website’s operating hours, calculate driving times, and maintain a mental budget.
          Dayform turns that upside down.
        </p>
      </div>

      {/* Scrollytelling Two-Column Layout */}
      <div className="story-stage-grid">
        {/* Left Column: Narrative Chapters with Progress Rail */}
        <div className="story-narrative-column">
          {/* Progress Indicator Rail */}
          <div className="story-rail-nav">
            {CHAPTERS.map((ch, idx) => (
              <button
                key={ch.id}
                type="button"
                className={`rail-pill ${activeStep === idx ? 'active' : ''}`}
                onClick={() => scrollToChapter(idx)}
                aria-label={`Jump to ${ch.tag}`}
              >
                <span className="rail-step-num">{ch.stepNumber}</span>
                <span className="rail-step-label">{ch.tag}</span>
              </button>
            ))}
          </div>

          {/* Narrative Chapters */}
          <div className="story-chapters-list">
            {CHAPTERS.map((chapter, index) => (
              <div
                key={chapter.id}
                ref={(el) => { chapterRefs.current[index] = el; }}
                className={`story-chapter-block ${activeStep === index ? 'in-focus' : 'dimmed'}`}
              >
                <div className="chapter-meta">
                  <span className="chapter-step-badge">{chapter.stepNumber}</span>
                  <span className="chapter-tag">{chapter.tag}</span>
                </div>

                <h3 className="chapter-title">{chapter.title}</h3>
                <p className="chapter-lead">{chapter.lead}</p>
                <p className="chapter-body">{chapter.body}</p>

                <div className="chapter-takeaway">
                  <span className="takeaway-bullet">→</span>
                  <span className="takeaway-text">{chapter.keyTakeaway}</span>
                </div>

                <div className="chapter-step-nav-row">
                  {index > 0 && (
                    <button
                      type="button"
                      className="btn-story-step prev"
                      onClick={() => scrollToChapter(index - 1)}
                    >
                      ← {CHAPTERS[index - 1].tag}
                    </button>
                  )}
                  {index < CHAPTERS.length - 1 ? (
                    <button
                      type="button"
                      className="btn-story-step next"
                      onClick={() => scrollToChapter(index + 1)}
                    >
                      Next: {CHAPTERS[index + 1].tag} →
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="btn-story-step cta"
                      onClick={() => onStartPlanning()}
                    >
                      Plan your day now →
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Right Column: Sticky Visual Morphing Stage */}
        <div className="story-visual-column">
          <div className="story-sticky-stage">
            <div className="stage-device-frame">
              {/* Stage Top Bar */}
              <div className="stage-top-bar">
                <div className="stage-dots">
                  <span className="dot" />
                  <span className="dot" />
                  <span className="dot" />
                </div>
                <div className="stage-title-pill">
                  <span className="stage-pulse-dot" />
                  <span>Dayform · {CHAPTERS[activeStep].tag}</span>
                </div>
                <div className="stage-step-controls">
                  <button
                    type="button"
                    className="stage-step-btn"
                    onClick={() => activeStep > 0 && scrollToChapter(activeStep - 1)}
                    disabled={activeStep === 0}
                    aria-label="Previous scene"
                  >
                    ‹
                  </button>
                  <span className="stage-step-tag">
                    0{activeStep + 1} / 06
                  </span>
                  <button
                    type="button"
                    className="stage-step-btn"
                    onClick={() => activeStep < CHAPTERS.length - 1 && scrollToChapter(activeStep + 1)}
                    disabled={activeStep === CHAPTERS.length - 1}
                    aria-label="Next scene"
                  >
                    ›
                  </button>
                </div>
              </div>

              {/* Dynamic Stage Canvas — Morphs with activeStep */}
              <div className="stage-canvas-content">
                {/* Scene 1: The Human Intention */}
                <div className={`scene-visual scene-1 ${activeStep === 0 ? 'active' : 'inactive'}`}>
                  <div className="scene-label">Raw Human Input</div>
                  <div className="intention-mock-bubble">
                    <p className="intention-text">
                      “I want to do something fun this <span className="highlight-tag">Saturday</span> with{' '}
                      <span className="highlight-tag">4 friends</span> in{' '}
                      <span className="highlight-tag">Cape Town</span> under{' '}
                      <span className="highlight-tag">R500</span> total.”
                    </p>
                    <span className="typing-cursor-line" />
                  </div>

                  <div className="intention-tags-row">
                    <span className="intent-chip">
                      <IconCalendar size={13} /> Weekend
                    </span>
                    <span className="intent-chip">
                      <IconUsers size={13} /> Small Group
                    </span>
                    <span className="intent-chip">
                      <IconWallet size={13} /> Strict Ceiling
                    </span>
                  </div>

                  <div className="scene-hint-box">
                    <IconSparkles size={14} className="hint-icon" />
                    <span>No structured form fields needed. Natural speech parsed directly.</span>
                  </div>
                </div>

                {/* Scene 2: Structured Context Extraction */}
                <div className={`scene-visual scene-2 ${activeStep === 1 ? 'active' : 'inactive'}`}>
                  <div className="scene-label">Extracted Structured Context</div>
                  <div className="context-cards-matrix">
                    <div className="context-metric-cell">
                      <div className="metric-header">
                        <IconCalendar size={14} />
                        <span>WHEN</span>
                      </div>
                      <div className="metric-val">Saturday afternoon</div>
                      <div className="metric-sub">Target start: 11:00 AM</div>
                    </div>

                    <div className="context-metric-cell">
                      <div className="metric-header">
                        <IconMapPin size={14} />
                        <span>WHERE</span>
                      </div>
                      <div className="metric-val">Cape Town</div>
                      <div className="metric-sub">City Bowl & Waterfront</div>
                    </div>

                    <div className="context-metric-cell">
                      <div className="metric-header">
                        <IconUsers size={14} />
                        <span>WHO</span>
                      </div>
                      <div className="metric-val">4 people</div>
                      <div className="metric-sub">Social pacing</div>
                    </div>

                    <div className="context-metric-cell highlight">
                      <div className="metric-header">
                        <IconWallet size={14} />
                        <span>BUDGET CEILING</span>
                      </div>
                      <div className="metric-val">R500 total</div>
                      <div className="metric-sub">~R125 per person</div>
                    </div>
                  </div>

                  <div className="scene-status-pill green">
                    <IconCheck size={14} />
                    <span>Context constraints locked · Feasibility verified</span>
                  </div>
                </div>

                {/* Scene 3: Evaluating Places & Live Hours */}
                <div className={`scene-visual scene-3 ${activeStep === 2 ? 'active' : 'inactive'}`}>
                  <div className="scene-label">Evaluating Real-World Options</div>
                  <div className="candidates-list-preview">
                    <div className="candidate-preview-item match">
                      <div className="item-icon-box">
                        <IconUtensils size={14} />
                      </div>
                      <div className="item-info">
                        <div className="item-name-row">
                          <span className="item-name">Truth Coffee Roasting</span>
                          <span className="item-score">Great match</span>
                        </div>
                        <div className="item-badge-row">
                          <span className="item-badge open">Open until 18:00</span>
                          <span className="item-badge cost">~R140</span>
                          <span className="item-badge distance">0.8km</span>
                        </div>
                      </div>
                      <IconCheckCircle size={16} className="item-check" />
                    </div>

                    <div className="candidate-preview-item match">
                      <div className="item-icon-box">
                        <IconPalette size={14} />
                      </div>
                      <div className="item-info">
                        <div className="item-name-row">
                          <span className="item-name">Zeitz MOCAA & Waterfront</span>
                          <span className="item-score">Scenic highlight</span>
                        </div>
                        <div className="item-badge-row">
                          <span className="item-badge open">Open until 18:00</span>
                          <span className="item-badge free">Free Entry / Public</span>
                          <span className="item-badge distance">1.4km</span>
                        </div>
                      </div>
                      <IconCheckCircle size={16} className="item-check" />
                    </div>

                    <div className="candidate-preview-item match">
                      <div className="item-icon-box">
                        <IconUtensils size={14} />
                      </div>
                      <div className="item-info">
                        <div className="item-name-row">
                          <span className="item-name">Honest Chocolate Cafe</span>
                          <span className="item-score">Budget friendly</span>
                        </div>
                        <div className="item-badge-row">
                          <span className="item-badge open">Open until 20:00</span>
                          <span className="item-badge cost">~R280</span>
                        </div>
                      </div>
                      <IconCheckCircle size={16} className="item-check" />
                    </div>
                  </div>

                  <div className="evaluation-tally">
                    <span className="tally-item">Candidate total: <strong>R420</strong></span>
                    <span className="tally-dot">·</span>
                    <span className="tally-item under"><strong>R80 under budget</strong></span>
                  </div>
                </div>

                {/* Scene 4: The Resolved Timed Itinerary */}
                <div className={`scene-visual scene-4 ${activeStep === 3 ? 'active' : 'inactive'}`}>
                  <div className="scene-label">Assembled Coherent Itinerary</div>
                  <div className="timeline-mock-track">
                    <div className="mock-stop-node">
                      <div className="stop-time-col">
                        <span className="stop-time">11:00</span>
                        <span className="stop-duration">60 min</span>
                      </div>
                      <div className="stop-marker" />
                      <div className="stop-card">
                        <div className="stop-title">Truth Coffee Roasting</div>
                        <div className="stop-desc">Kick off with artisanal coffee and briefing</div>
                        <div className="stop-meta">Cape Town City Centre · ~R140</div>
                      </div>
                    </div>

                    <div className="mock-transit-gap">
                      <span className="gap-line" />
                      <span className="gap-label">15 min scenic stroll</span>
                      <span className="gap-line" />
                    </div>

                    <div className="mock-stop-node">
                      <div className="stop-time-col">
                        <span className="stop-time">12:15</span>
                        <span className="stop-duration">90 min</span>
                      </div>
                      <div className="stop-marker" />
                      <div className="stop-card">
                        <div className="stop-title">Zeitz MOCAA & Silo District</div>
                        <div className="stop-desc">Contemporary art & harbor architecture</div>
                        <div className="stop-meta">Silo District · Free / Public areas</div>
                      </div>
                    </div>

                    <div className="mock-transit-gap">
                      <span className="gap-line" />
                      <span className="gap-label">10 min transit</span>
                      <span className="gap-line" />
                    </div>

                    <div className="mock-stop-node">
                      <div className="stop-time-col">
                        <span className="stop-time">14:00</span>
                        <span className="stop-duration">60 min</span>
                      </div>
                      <div className="stop-marker" />
                      <div className="stop-card">
                        <div className="stop-title">Honest Chocolate Cafe</div>
                        <div className="stop-desc">Craft chocolate treats and courtyard chat</div>
                        <div className="stop-meta">Wale Street · ~R280 for group</div>
                      </div>
                    </div>
                  </div>

                  <div className="itinerary-summary-bar">
                    <span>3 Stops · 4 hours · R420 total (R80 buffer)</span>
                  </div>
                </div>

                {/* Scene 5: Conversational Adaptation */}
                <div className={`scene-visual scene-5 ${activeStep === 4 ? 'active' : 'inactive'}`}>
                  <div className="scene-label">Adaptive Recalibration</div>

                  {/* Incoming user tweak */}
                  <div className="tweak-incoming-bubble">
                    <div className="tweak-avatar">You</div>
                    <div className="tweak-bubble-body">
                      “Actually, we’re running 45 minutes late.”
                    </div>
                  </div>

                  {/* Adaptation Diff Banner */}
                  <div className="adaptation-event-banner">
                    <IconSparkles size={14} className="sparkle-amber" />
                    <span>Timeline re-sequenced · Downstream times adjusted</span>
                  </div>

                  {/* Diff representation */}
                  <div className="diff-timeline-preview">
                    <div className="diff-row">
                      <div className="diff-time-pair">
                        <span className="old-time">11:00</span>
                        <span className="arrow">→</span>
                        <span className="new-time">11:45</span>
                      </div>
                      <div className="diff-info">
                        <span className="diff-name">Truth Coffee</span>
                        <span className="diff-tag shift">+45m shift</span>
                      </div>
                    </div>

                    <div className="diff-row">
                      <div className="diff-time-pair">
                        <span className="old-time">12:15</span>
                        <span className="arrow">→</span>
                        <span className="new-time">13:00</span>
                      </div>
                      <div className="diff-info">
                        <span className="diff-name">Zeitz MOCAA</span>
                        <span className="diff-tag shift">+45m shift</span>
                      </div>
                    </div>

                    <div className="diff-row">
                      <div className="diff-time-pair">
                        <span className="old-time">14:00</span>
                        <span className="arrow">→</span>
                        <span className="new-time">14:45</span>
                      </div>
                      <div className="diff-info">
                        <span className="diff-name">Honest Chocolate</span>
                        <span className="diff-tag verified">Verified open until 20:00</span>
                      </div>
                    </div>
                  </div>

                  <div className="scene-status-pill green">
                    <IconCheck size={14} />
                    <span>Opening hours verified · Schedule preserved without conflict</span>
                  </div>
                </div>

                {/* Scene 6: Real-World Execution & CTA */}
                <div className={`scene-visual scene-6 ${activeStep === 5 ? 'active' : 'inactive'}`}>
                  <div className="scene-label">Execution & Live Action</div>

                  <div className="execution-action-preview">
                    <div className="exec-card">
                      <div className="exec-header">
                        <div className="exec-title">Active Step: Truth Coffee Roasting</div>
                        <span className="live-pulse-badge">Verified Open</span>
                      </div>

                      <div className="exec-buttons-row">
                        <button type="button" className="mock-exec-btn primary">
                          <IconNavigation size={13} />
                          <span>Google Maps</span>
                        </button>
                        <button type="button" className="mock-exec-btn">
                          <IconPhone size={13} />
                          <span>Call Venue</span>
                        </button>
                      </div>
                    </div>

                    <div className="cta-invitation-box">
                      <h4 className="cta-box-title">Ready to plan your next outing?</h4>
                      <p className="cta-box-desc">
                        No accounts to sign up for. No credit cards. Try an intention right now.
                      </p>
                      <button
                        type="button"
                        className="cta-action-button"
                        onClick={() => onStartPlanning()}
                      >
                        <span>Start your plan now</span>
                        <IconArrowRight size={15} />
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
};
