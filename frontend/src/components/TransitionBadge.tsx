import React from 'react';
import type { PlanTransitionRead } from '../types/planning';
import {
  IconWalk,
  IconBus,
  IconTrain,
  IconCar,
  IconNavigation,
  IconExternalLink,
  IconAlertCircle,
} from './Icons';

interface TransitionBadgeProps {
  transition: PlanTransitionRead;
  className?: string;
}

/** M16 live state, expressed for the user without overstating what is known. */
function describeLiveState(transition: PlanTransitionRead): {
  tone: 'live' | 'warn' | 'alert' | 'muted';
  label: string;
} | null {
  const availability = transition.live_availability ?? 'unavailable';
  const status = (transition.live_status || 'unknown').toLowerCase();

  // A provider with no live source is described as such, never as "live".
  if (availability === 'unavailable') {
    return { tone: 'muted', label: 'No live feed' };
  }
  if (availability === 'stale' || status === 'unknown') {
    return { tone: 'muted', label: 'Live status unavailable' };
  }
  if (status === 'operating_normal' || status === 'live' || status === 'on_time') {
    return { tone: 'live', label: 'Live · operating normally' };
  }
  if (status === 'delayed') {
    const delay = transition.live_delay_minutes;
    return {
      tone: 'warn',
      label: delay ? `Live · delayed ${delay} min` : 'Live · delayed',
    };
  }
  if (status === 'disrupted') return { tone: 'alert', label: 'Live · disrupted' };
  if (status === 'cancelled') return { tone: 'alert', label: 'Live · cancelled' };
  if (status === 'service_unavailable') {
    return { tone: 'alert', label: 'Live · service unavailable' };
  }
  return { tone: 'muted', label: 'Live status unavailable' };
}

export const TransitionBadge: React.FC<TransitionBadgeProps> = ({
  transition,
  className = '',
}) => {
  const modeNorm = transition.mode.toLowerCase();

  const renderIcon = () => {
    switch (modeNorm) {
      case 'walk':
      case 'walking':
        return <IconWalk size={13} className="transition-mode-icon" />;
      case 'bus':
        return <IconBus size={13} className="transition-mode-icon" />;
      case 'train':
      case 'rail':
        return <IconTrain size={13} className="transition-mode-icon" />;
      case 'ride_hail':
      case 'ride_share':
      case 'car':
        return <IconCar size={13} className="transition-mode-icon" />;
      default:
        return <IconNavigation size={13} className="transition-mode-icon" />;
    }
  };

  const costLabel = transition.cost_known && transition.cost !== null
    ? `R${Number(transition.cost).toFixed(2)}`
    : transition.mode === 'walk'
    ? 'Free'
    : 'Fare in app';

  const live = describeLiveState(transition);

  return (
    <div
      className={`plan-transition-badge-wrapper ${!transition.is_feasible ? 'has-feasibility-issue' : ''} ${className}`}
    >
      <div className="plan-transition-badge">
        <div className="transition-badge-core">
          {renderIcon()}
          <span className="transition-provider">{transition.provider_name}</span>
          {transition.duration_minutes !== null && (
            <>
              <span className="transition-dot">·</span>
              <span className="transition-duration">~{transition.duration_minutes} min</span>
            </>
          )}
          <span className="transition-dot">·</span>
          <span className="transition-cost">{costLabel}</span>

          {transition.booking_url && (
            <a
              href={transition.booking_url}
              target="_blank"
              rel="noopener noreferrer"
              className="transition-booking-link"
              title={`Open ${transition.provider_name}`}
            >
              <span>Book</span>
              <IconExternalLink size={10} />
            </a>
          )}
        </div>

        {live && (
          <div
            className={`transition-live-tag tone-${live.tone}`}
            title={
              transition.live_explanation ||
              'Live service status is not available for this provider.'
            }
          >
            <span className="live-dot" />
            <span>{live.label}</span>
          </div>
        )}
      </div>

      {!transition.is_feasible && transition.feasibility_issue && (
        <div className="transition-feasibility-alert">
          <IconAlertCircle size={12} />
          <span>{transition.feasibility_issue}</span>
        </div>
      )}
    </div>
  );
};
