import React from 'react';
import type { OrchestratedPlanRead, UnderstandingRead } from '../types/planning';
import { dayBounds, planSummaryLine, planTitle } from '../utils/planVoice';
import type { StopInput } from '../utils/planVoice';
import { formatCurrency } from '../utils/itineraryBuilder';
import { IconClock } from './Icons';

interface PlanIdentityProps {
  understanding: UnderstandingRead | null | undefined;
  items: StopInput[];
  orchestrated: OrchestratedPlanRead | null | undefined;
  fallbackSpan?: string;
  totalCost?: number;
  totalCostLabel?: string;
  budgetMax?: number | null;
  isOverBudget?: boolean;
  hasUnknownCosts?: boolean;
}

/**
 * The plan's identity.
 *
 * "YOUR DAY" tells the user nothing about the day they asked for. This names it
 * after what is actually in it, and shows the real span and cost of the day underneath —
 * read from the scheduled stops rather than from the client's pre-orchestration
 * estimate, so the two can never disagree about when the day ends.
 */
export const PlanIdentity: React.FC<PlanIdentityProps> = ({
  understanding,
  items,
  orchestrated,
  fallbackSpan,
  totalCost,
  totalCostLabel,
  budgetMax,
  isOverBudget,
  hasUnknownCosts = false,
}) => {
  const title = planTitle(understanding, items);
  const summary = planSummaryLine(items);
  const bounds = dayBounds(orchestrated, fallbackSpan);
  const budgetBudgeted = budgetMax !== null && budgetMax !== undefined;

  return (
    <div className="df-identity df-light df-light--still">
      <p className="df-identity-eyebrow">Your plan</p>
      <h2 className="df-identity-title">{title}</h2>
      <p className="df-identity-summary">{summary}</p>
      <div className="df-identity-meta-row">
        {bounds.start && bounds.end && (
          <p className={`df-identity-bounds ${bounds.fromItinerary ? 'is-verified' : 'is-estimate'}`}>
            <IconClock size={12} />
            <span>
              {bounds.start} – {bounds.end}
            </span>
            <span className="df-identity-bounds-note">
              {bounds.fromItinerary
                ? 'Times follow the itinerary'
                : 'Estimated span'}
            </span>
          </p>
        )}
        {totalCost !== undefined && (
          <p className={`df-identity-bounds df-identity-budget ${isOverBudget ? 'is-over' : hasUnknownCosts ? 'is-unverified' : 'is-verified'}`}>
            <span>
              {totalCostLabel ?? (budgetBudgeted ? `${formatCurrency(totalCost)} of ${formatCurrency(budgetMax)}` : `${formatCurrency(totalCost)} planned`)}
            </span>
            {budgetBudgeted && (
              <span className="df-identity-bounds-note">
                {isOverBudget ? '· Over limit' : hasUnknownCosts ? '· Some prices unavailable' : '· In budget'}
              </span>
            )}
          </p>
        )}
      </div>
    </div>
  );
};

