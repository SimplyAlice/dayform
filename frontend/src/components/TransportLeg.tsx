import React, { useState, useRef, useEffect } from 'react';
import type { OrchestratedLegRead, MobilityOptionRead } from '../types/planning';
import {
  IconWalk,
  IconBus,
  IconTrain,
  IconCar,
  IconNavigation,
  IconCheck,
  IconAlertCircle,
  IconArrowUpRight,
  IconX,
} from './Icons';

export interface TransportLegProps {
  leg: OrchestratedLegRead;
  legIndex?: number;
  onSelectOption?: (legIndex: number, optionId: string) => void;
}

function modeIcon(mode?: string, pid?: string) {
  const normMode = (mode || '').toLowerCase();
  const normPid = (pid || '').toLowerCase();
  if (normPid === 'walking' || normMode === 'walk' || normMode === 'walking') {
    return <IconWalk size={15} className="transport-mode-glyph" />;
  }
  if (normPid === 'myciti' || normPid === 'golden_arrow' || normMode === 'bus') {
    return <IconBus size={15} className="transport-mode-glyph" />;
  }
  if (normPid === 'prasa_metrorail' || normMode === 'train' || normMode === 'rail') {
    return <IconTrain size={15} className="transport-mode-glyph" />;
  }
  if (['uber', 'bolt', 'indrive'].includes(normPid) || ['ride_hail', 'ride_share', 'car'].includes(normMode)) {
    return <IconCar size={15} className="transport-mode-glyph" />;
  }
  return <IconNavigation size={15} className="transport-mode-glyph" />;
}

function getProviderDisplayName(option: MobilityOptionRead): string {
  const pid = (option.provider_id || '').toLowerCase();
  if (pid === 'prasa_metrorail' || pid.includes('metrorail')) return 'Metrorail';
  if (pid === 'myciti') return 'MyCiTi';
  if (pid === 'golden_arrow') return 'Golden Arrow';
  if (pid === 'uber') return 'Uber';
  if (pid === 'bolt') return 'Bolt';
  if (pid === 'indrive') return 'inDrive';
  if (pid === 'walking' || option.mode?.toLowerCase() === 'walk') return 'Walking';
  return option.provider_name || 'Transport';
}

function getDurationDisplay(option: MobilityOptionRead): string {
  const minutes = option.duration_minutes;
  if (minutes === null || minutes === undefined) {
    return 'Travel time unavailable';
  }
  return `~${minutes} min`;
}

function getFareDisplay(option: MobilityOptionRead): { label: string; isEstimated: boolean } {
  const pid = (option.provider_id || '').toLowerCase();
  const mode = (option.mode || '').toLowerCase();

  if (pid === 'walking' || mode === 'walk') {
    return { label: 'Free', isEstimated: false };
  }

  if (['uber', 'bolt', 'indrive'].includes(pid)) {
    const brand = pid === 'uber' ? 'Uber' : pid === 'bolt' ? 'Bolt' : 'inDrive';
    return { label: `Fare calculated in ${brand}`, isEstimated: false };
  }

  if (option.cost_is_unknown || option.cost === null || option.cost === undefined) {
    return { label: 'Fare unavailable', isEstimated: false };
  }

  const num = Number(option.cost);
  if (isNaN(num)) {
    return { label: 'Fare unavailable', isEstimated: false };
  }

  const formatted = `R${num.toFixed(2)}`;
  if (option.cost_is_estimated) {
    return { label: `Estimated fare: ${formatted}`, isEstimated: true };
  }
  return { label: formatted, isEstimated: false };
}

function getActionLabel(option: MobilityOptionRead): string {
  const pid = (option.provider_id || '').toLowerCase();
  const mode = (option.mode || '').toLowerCase();
  if (option.action_label) return option.action_label;
  if (pid === 'walking' || mode === 'walk') return 'Walking directions';
  if (pid === 'uber') return 'Open Uber';
  if (pid === 'bolt') return 'Open Bolt';
  if (pid === 'indrive') return 'Open inDrive';
  if (pid === 'prasa_metrorail' || pid.includes('metrorail')) return 'View PRASA timetable';
  if (pid === 'myciti') return 'View MyCiTi timetable';
  if (pid === 'golden_arrow') return 'View Golden Arrow timetable';
  return 'View timetable';
}

function getActionUrl(option: MobilityOptionRead, fromLabel?: string, toLabel?: string): string | null {
  if (option.booking_url) return option.booking_url;
  const pid = (option.provider_id || '').toLowerCase();
  const mode = (option.mode || '').toLowerCase();
  const fromEncoded = encodeURIComponent(fromLabel || 'Cape Town');
  const toEncoded = encodeURIComponent(toLabel || 'Cape Town');

  if (pid === 'walking' || mode === 'walk') {
    return `https://www.google.com/maps/dir/?api=1&origin=${fromEncoded}&destination=${toEncoded}&travelmode=walking`;
  }
  if (pid === 'prasa_metrorail' || pid.includes('metrorail')) {
    return 'https://cttrains.co.za/';
  }
  if (pid === 'myciti') {
    return 'https://www.myciti.org.za/en/routes-timetables/';
  }
  if (pid === 'golden_arrow') {
    return 'https://gabs.co.za/timetables/';
  }
  if (pid === 'uber') {
    return `https://m.uber.com/ul/?action=setPickup&pickup=my_location&dropoff[formatted_address]=${toEncoded}`;
  }
  if (pid === 'bolt') {
    return 'https://bolt.eu/';
  }
  if (pid === 'indrive') {
    return 'https://indrive.com/';
  }
  return null;
}

function getRouteBadge(option: MobilityOptionRead): string | null {
  if (option.route_or_line && option.route_or_line.trim()) {
    return option.route_or_line.trim();
  }
  const summary = option.summary || '';
  if (summary.includes('Southern Line')) return 'Southern Line';
  if (summary.includes('Northern Line')) return 'Northern Line';
  const pid = (option.provider_id || '').toLowerCase();
  if (pid === 'prasa_metrorail') return 'Passenger Rail';
  if (pid === 'myciti') return 'Bus Route';
  return null;
}

function getServiceNotes(option: MobilityOptionRead): {
  typeLabel: string;
  truthBadges: Array<{ text: string; tone: 'scheduled' | 'live-unverified' | 'on-demand' | 'walk' }>;
  detailNote: string;
} {
  const pid = (option.provider_id || '').toLowerCase();
  const mode = (option.mode || '').toLowerCase();
  const badges: Array<{ text: string; tone: 'scheduled' | 'live-unverified' | 'on-demand' | 'walk' }> = [];

  let typeLabel = 'Scheduled Transit';
  let detailNote = '';

  if (pid === 'walking' || mode === 'walk') {
    typeLabel = 'Pedestrian route';
    badges.push({ text: 'Walking route', tone: 'walk' });
    detailNote = 'Standard pedestrian route. No vehicle needed.';
    return { typeLabel, truthBadges: badges, detailNote };
  }

  if (['uber', 'bolt', 'indrive'].includes(pid)) {
    typeLabel = 'On-demand ride';
    badges.push({ text: 'On-demand · Variable wait', tone: 'on-demand' });
    detailNote = 'Real-time booking via ride-hailing app. Wait times and surge pricing depend on driver availability.';
    return { typeLabel, truthBadges: badges, detailNote };
  }

  if (pid === 'prasa_metrorail' || pid.includes('metrorail')) {
    typeLabel = 'PRASA Metrorail';
    badges.push({ text: 'Scheduled timetable · Unverified live status', tone: 'live-unverified' });
    detailNote = 'Timetable-based planning. Live delays or cancellations cannot be verified in real-time.';
    return { typeLabel, truthBadges: badges, detailNote };
  }

  if (pid === 'myciti') {
    typeLabel = 'MyCiTi Bus';
    badges.push({ text: 'Scheduled timetable · High frequency', tone: 'scheduled' });
    detailNote = 'Dedicated bus lane network. Requires a myconnect smart card.';
    return { typeLabel, truthBadges: badges, detailNote };
  }

  if (pid === 'golden_arrow') {
    typeLabel = 'Golden Arrow Bus';
    badges.push({ text: 'Scheduled timetable · Cash/card', tone: 'scheduled' });
    detailNote = 'Regional bus service across the Cape Peninsula. Check timetable for off-peak frequency.';
    return { typeLabel, truthBadges: badges, detailNote };
  }

  badges.push({ text: 'Scheduled timetable', tone: 'scheduled' });
  detailNote = 'Based on published transit timetable.';
  return { typeLabel, truthBadges: badges, detailNote };
}

export const TransportLeg: React.FC<TransportLegProps> = ({
  leg,
  legIndex = 0,
  onSelectOption,
}) => {
  const [showCompare, setShowCompare] = useState(false);
  const popoverRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const allOptions: MobilityOptionRead[] = leg.all_options || leg.alternatives || [];
  const selectedOption: MobilityOptionRead | undefined =
    allOptions.find((o) => o.id === leg.selected_option_id) || allOptions[0];
  const transition = leg.transition;

  // Elevate parent plan card stacking context when compare popover is open
  useEffect(() => {
    if (!containerRef.current) return;
    const closestEntry = containerRef.current.closest<HTMLElement>(
      '.journey-entry, .saved-stop-node, .saved-origin-leg-wrap'
    );
    if (closestEntry) {
      if (showCompare) {
        closestEntry.classList.add('has-popover-open');
      } else {
        closestEntry.classList.remove('has-popover-open');
      }
    }
    return () => {
      if (closestEntry) {
        closestEntry.classList.remove('has-popover-open');
      }
    };
  }, [showCompare]);

  // Close popover when clicking outside or pressing Escape
  useEffect(() => {
    if (!showCompare) return;

    const handleClickOutside = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setShowCompare(false);
      }
    };

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setShowCompare(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleKeyDown);

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [showCompare]);

  if (!selectedOption) {
    return (
      <div className="transport-leg-container transport-leg-unknown">
        <div className="transport-segment-rule" />
        <div className="transport-leg-card">
          <div className="transport-leg-primary-row">
            <div className="transport-mode-badge transport-mode-badge-neutral">
              <IconNavigation size={15} />
            </div>
            <div className="transport-leg-summary">
              <span className="transport-provider-name">Transit between stops</span>
              <span className="transport-duration-tag">
                {transition.duration_minutes ? `~${transition.duration_minutes} min` : 'Duration varies'}
              </span>
            </div>
          </div>
          {leg.preference_note && (
            <p className="transport-preference-note">{leg.preference_note}</p>
          )}
        </div>
      </div>
    );
  }

  const selectedFare = getFareDisplay(selectedOption);
  const selectedDuration = getDurationDisplay(selectedOption);
  const selectedProviderName = getProviderDisplayName(selectedOption);
  const selectedRouteBadge = getRouteBadge(selectedOption);
  const selectedActionLabel = getActionLabel(selectedOption);
  const selectedActionUrl = getActionUrl(selectedOption, leg.from_label, leg.to_label);
  const selectedNotes = getServiceNotes(selectedOption);

  const alternativeOptions: MobilityOptionRead[] =
    leg.alternatives && leg.alternatives.length > 0
      ? leg.alternatives.filter((o: MobilityOptionRead) => o.id !== selectedOption.id)
      : allOptions.filter((o: MobilityOptionRead) => o.id !== selectedOption.id);

  const handleSelect = (optionId: string, e?: React.MouseEvent) => {
    if (e) e.stopPropagation();
    if (onSelectOption) {
      onSelectOption(legIndex, optionId);
    }
  };

  return (
    <div
      ref={containerRef}
      className={`transport-leg-container ${showCompare ? 'is-popover-open' : ''}`}
      data-leg-index={legIndex}
    >
      {/* Route Connector Line */}
      <div className="transport-segment-rule" aria-hidden="true" />

      {/* Main Transport Card */}
      <div className={`transport-leg-card ${showCompare ? 'is-popover-open' : ''}`}>
        <div className="transport-leg-primary-row">
          <div className="transport-mode-group">
            <span
              className="transport-mode-badge transport-mode-circle"
              aria-label={`Transport mode: ${selectedOption.mode || 'transit'}`}
            >
              {modeIcon(selectedOption.mode, selectedOption.provider_id)}
            </span>

            <div className="transport-leg-summary">
              <div className="transport-name-row">
                <span className="transport-provider-name">{selectedProviderName}</span>
                {selectedRouteBadge && (
                  <span className="transport-route-badge transport-route-pill">{selectedRouteBadge}</span>
                )}
                {Boolean(selectedOption && leg.selected_option_id && selectedOption.id === leg.selected_option_id) && (
                  <span className="transport-selected-pill" title="Selected option for this journey">
                    <IconCheck size={10} />
                    <span>Chosen</span>
                  </span>
                )}
              </div>

              <div className="transport-meta-metrics">
                <span className="transport-duration-tag">{selectedDuration}</span>
                <span className="transport-metric-separator">·</span>
                <span className={`transport-cost-tag ${selectedFare.isEstimated ? 'is-estimated' : ''}`}>
                  {selectedFare.label}
                </span>
                {leg.from_label && leg.to_label && (
                  <>
                    <span className="transport-metric-separator">·</span>
                    <span className="transport-endpoints-hint">
                      {leg.from_label} → {leg.to_label}
                    </span>
                  </>
                )}
              </div>
            </div>
          </div>

          <div className="transport-primary-actions">
            {selectedActionUrl && (
              <a
                href={selectedActionUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="transport-action-btn transport-action-cta"
                title={`${selectedActionLabel} (opens in new window)`}
                onClick={(e) => e.stopPropagation()}
              >
                <span>{selectedActionLabel}</span>
                <IconArrowUpRight size={13} />
              </a>
            )}

            {/* Compact Compare Transport Trigger */}
            {alternativeOptions.length > 0 && (
              <div className="compare-transport-anchor">
                <button
                  type="button"
                  className="btn-compare-transport"
                  onClick={(e) => {
                    e.stopPropagation();
                    setShowCompare((prev) => !prev);
                  }}
                  aria-expanded={showCompare}
                  aria-haspopup="dialog"
                  title="Compare viable transport options for this leg"
                >
                  <span>Compare transport</span>
                  <span className="compare-count-tag">{alternativeOptions.length}</span>
                </button>

                {showCompare && (
                  <div
                    ref={popoverRef}
                    className="compare-transport-popover animate-fade-in"
                    role="dialog"
                    aria-label="Compare transport alternatives"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <div className="compare-popover-header">
                      <span className="compare-popover-title">Alternative transport</span>
                      <button
                        type="button"
                        className="btn-popover-close"
                        onClick={() => setShowCompare(false)}
                        aria-label="Close"
                      >
                        <IconX size={12} />
                      </button>
                    </div>

                    <div className="compare-popover-list">
                      {alternativeOptions.map((opt: MobilityOptionRead) => {
                        const optFare = getFareDisplay(opt);
                        const optDuration = getDurationDisplay(opt);
                        const optProviderName = getProviderDisplayName(opt);
                        const optRouteBadge = getRouteBadge(opt);
                        const optNotes = getServiceNotes(opt);

                        return (
                          <div key={opt.id} className="compare-popover-row">
                            <div className="compare-popover-info">
                              <div className="compare-popover-name-row">
                                <span className="transport-mode-badge-mini">
                                  {modeIcon(opt.mode, opt.provider_id)}
                                </span>
                                <span className="compare-popover-provider">{optProviderName}</span>
                                {optRouteBadge && (
                                  <span className="transport-route-pill-mini">{optRouteBadge}</span>
                                )}
                              </div>

                              <div className="compare-popover-metrics">
                                <span>{optDuration}</span>
                                <span className="metric-dot">·</span>
                                <span>{optFare.label}</span>
                              </div>

                              {optNotes.truthBadges.length > 0 && (
                                <div className="compare-popover-badges">
                                  {optNotes.truthBadges.map((badge, bIdx) => (
                                    <span key={bIdx} className={`transport-truth-badge mini ${badge.tone}`}>
                                      {badge.text}
                                    </span>
                                  ))}
                                </div>
                              )}
                            </div>

                            <button
                              type="button"
                              className="btn-switch-transport-compact"
                              onClick={(e) => {
                                handleSelect(opt.id, e);
                                setShowCompare(false);
                              }}
                            >
                              Switch
                            </button>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Selected Honest Status Badges */}
        <div className="transport-truth-strip transport-truth-row">
          {selectedNotes.truthBadges.map((badge, bIdx) => (
            <span key={bIdx} className={`transport-truth-badge ${badge.tone}`}>
              {badge.text}
            </span>
          ))}
        </div>

        {/* Selected Context Note */}
        {selectedNotes.detailNote && (
          <p className="transport-card-note">{selectedNotes.detailNote}</p>
        )}

        {/* Leg Warnings / Substitutions if any */}
        {leg.preference_honoured === false && leg.preference_note && (
          <div className="transport-leg-warning transport-advisory-banner">
            <IconAlertCircle size={13} />
            <span>{leg.preference_note}</span>
          </div>
        )}

        {!transition.is_feasible && transition.feasibility_issue && (
          <div className="transport-leg-warning transport-advisory-banner alert">
            <IconAlertCircle size={13} />
            <span>{transition.feasibility_issue}</span>
          </div>
        )}
      </div>
    </div>
  );
};
