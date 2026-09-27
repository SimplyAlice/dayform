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

        {transition.live_status && transition.live_status !== 'unknown' && transition.live_status !== 'normal' && (
          <div className="transition-live-tag">
            <span className="live-dot" />
            <span>{transition.live_status.toUpperCase()}</span>
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
