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
  fromLabel?: string;
  toLabel?: string;
}

function getTransitionActionUrl(
  transition: PlanTransitionRead,
  fromLabel?: string,
  toLabel?: string
): string | null {
  if (transition.booking_url) return transition.booking_url;
  const pid = (transition.provider_id || '').toLowerCase();
  const mode = (transition.mode || '').toLowerCase();
  const fromEncoded = encodeURIComponent(fromLabel || 'Cape Town');
  const toEncoded = encodeURIComponent(toLabel || 'Cape Town');

  if (pid === 'walking' || mode === 'walk' || mode === 'walking') {
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

function getTransitionActionLabel(transition: PlanTransitionRead): string {
  const pid = (transition.provider_id || '').toLowerCase();
  const mode = (transition.mode || '').toLowerCase();
  if (pid === 'walking' || mode === 'walk' || mode === 'walking') return 'Walking directions';
  if (pid === 'uber') return 'Open Uber';
  if (pid === 'bolt') return 'Open Bolt';
  if (pid === 'indrive') return 'Open inDrive';
  if (pid === 'prasa_metrorail' || pid.includes('metrorail')) return 'PRASA timetable';
  if (pid === 'myciti') return 'MyCiTi timetable';
  if (pid === 'golden_arrow') return 'Golden Arrow timetable';
  return 'Timetable';
}

/** M16 live state, expressed for the user without overstating what is known. */
function describeLiveState(transition: PlanTransitionRead): {
  tone: 'live' | 'warn' | 'alert' | 'muted';
  label: string;
} | null {
  const availability = transition.live_availability ?? 'unavailable';
  const status = (transition.live_status || 'unknown').toLowerCase();

  // A provider with no live source is described as such, never as "live". A
  // provider that reports its own service as unavailable is in the same
  // position from the user's point of view: there is no live feed to show.
  if (availability === 'unavailable' || status === 'service_unavailable') {
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
  return { tone: 'muted', label: 'Live status unavailable' };
}

export const TransitionBadge: React.FC<TransitionBadgeProps> = ({
  transition,
  className = '',
  fromLabel,
  toLabel,
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

  const providerLabel = transition.provider_name?.trim()
    ? transition.provider_name
    : 'Transport provider unavailable';

  const durationLabel =
    transition.duration_minutes !== null && transition.duration_minutes !== undefined
      ? `~${transition.duration_minutes} min`
      : 'Travel time unavailable';

  const actionLabel = getTransitionActionLabel(transition);
  const actionUrl = getTransitionActionUrl(transition, fromLabel, toLabel);

  const costLabel =
    transition.mode.toLowerCase() === 'walk' || transition.provider_id === 'walking'
      ? 'Free'
      : ['uber', 'bolt', 'indrive'].includes(transition.provider_id) && !transition.cost_known
      ? 'Fare confirmed in app'
      : transition.cost_known && transition.cost !== null
      ? transition.cost_is_estimated
        ? `R${Number(transition.cost).toFixed(2)} estimated`
        : `R${Number(transition.cost).toFixed(2)}`
      : 'Cost unavailable';

  const live = describeLiveState(transition);

  return (
    <div
      className={`plan-transition-badge-wrapper ${!transition.is_feasible ? 'has-feasibility-issue' : ''} ${className}`}
    >
      <div className="plan-transition-badge">
        <div className="transition-badge-core">
          {renderIcon()}
          <span className="transition-provider">{providerLabel}</span>
          <span className="transition-dot">·</span>
          <span className="transition-duration">{durationLabel}</span>
          <span className="transition-dot">·</span>
          <span className="transition-cost">{costLabel}</span>

          {actionUrl && (
            <a
              href={actionUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="transition-booking-link"
              title={`${actionLabel} (opens in new window)`}
            >
              <span>{actionLabel}</span>
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
