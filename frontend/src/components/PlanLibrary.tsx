import React, { useEffect, useState } from 'react';
import type { PlanRead } from '../types/planning';
import { listPlans } from '../api/planning';
import {
  IconCalendar,
  IconClock,
  IconArrowRight,
  IconPlus,
  IconMapPin,
  IconCheck,
  IconAlertCircle,
} from './Icons';

interface PlanLibraryProps {
  onOpenPlan: (planId: string) => Promise<void>;
  onNewPlan: () => void;
}

export const PlanLibrary: React.FC<PlanLibraryProps> = ({ onOpenPlan, onNewPlan }) => {
  const [plans, setPlans] = useState<PlanRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [openingId, setOpeningId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listPlans()
      .then((data) => {
        if (cancelled) return;
        // Sort newest first
        const sorted = [...data].sort((a, b) => {
          const tA = new Date(b.created_at || '').getTime();
          const tB = new Date(a.created_at || '').getTime();
          return tA - tB;
        });
        setPlans(sorted);
      })
      .catch((err) => {
        if (cancelled) return;
        console.error('Failed to load library plans:', err);
        setError('Could not load saved plans. Please try again.');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const handleOpen = async (planId: string) => {
    setOpeningId(planId);
    try {
      await onOpenPlan(planId);
    } catch (err) {
      console.error('Error opening plan:', err);
      setError('Could not open this plan.');
    } finally {
      setOpeningId(null);
    }
  };

  const formatPlannedDateTime = (startTime?: string | null) => {
    if (!startTime) return 'Flexible time';
    try {
      const dt = new Date(startTime);
      if (isNaN(dt.getTime())) return 'Flexible time';
      return dt.toLocaleDateString('en-ZA', {
        weekday: 'short',
        day: 'numeric',
        month: 'short',
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return 'Flexible time';
    }
  };

  const calculateTotalCost = (plan: PlanRead) => {
    if (!plan.items || plan.items.length === 0) {
      const budget = plan.constraints?.find((c) => c.type === 'budget_max');
      if (budget?.numeric_value) return `Budget: R${budget.numeric_value}`;
      return 'Free / no cost recorded';
    }
    let total = 0;
    let hasKnown = false;
    for (const it of plan.items) {
      if (it.estimated_cost !== null && it.estimated_cost !== undefined) {
        total += Number(it.estimated_cost);
        hasKnown = true;
      }
    }
    if (!hasKnown) return 'Cost varies';
    if (total === 0) return 'Free entry';
    return `R${total.toFixed(0)}`;
  };

  return (
    <div className="plan-library-stage animate-fade-in">
      <div className="library-header-strip">
        <div className="library-title-group">
          <span className="library-kicker">YOUR COLLECTION</span>
          <h1 className="library-headline">Plan Library</h1>
          <p className="library-lead">
            Every itinerary you have shaped and saved, ready to reopen and explore.
          </p>
        </div>
        <button type="button" className="btn-magazine-primary" onClick={onNewPlan}>
          <IconPlus size={15} />
          <span>New plan</span>
        </button>
      </div>

      {error && (
        <div className="library-error-banner" role="alert">
          <IconAlertCircle size={16} />
          <span>{error}</span>
        </div>
      )}

      {loading ? (
        <div className="library-loading-state">
          <span className="cta-spinner" />
          <p>Loading your saved plans…</p>
        </div>
      ) : plans.length === 0 ? (
        <div className="library-empty-state">
          <div className="empty-mark">
            <IconCalendar size={32} />
          </div>
          <h2 className="empty-title">No saved plans yet</h2>
          <p className="empty-sub">
            Describe the day you want on the home page, tweak the recommendations, and click “Save plan” to keep it here.
          </p>
          <button type="button" className="btn-magazine-primary hero-size" onClick={onNewPlan}>
            <span>Plan your first day</span>
            <IconArrowRight size={16} />
          </button>
        </div>
      ) : (
        <div className="library-grid">
          {plans.map((plan) => {
            const title = plan.title || plan.intention || 'Untitled plan';
            const dateStr = formatPlannedDateTime(plan.context?.start_time);
            const costStr = calculateTotalCost(plan);
            const stopCount = plan.items ? plan.items.length : 0;
            const location = plan.context?.location || 'Cape Town';
            const isOpening = openingId === plan.id;

            return (
              <article key={plan.id} className="library-card">
                <div className="library-card-body">
                  <div className="library-card-top">
                    <span className="library-status-badge">
                      <IconCheck size={11} />
                      <span>{plan.status === 'ready' ? 'Ready' : 'Saved'}</span>
                    </span>
                    <span className="library-date-badge">
                      <IconClock size={12} />
                      <span>{dateStr}</span>
                    </span>
                  </div>

                  <h3 className="library-card-title">{title}</h3>

                  <div className="library-card-meta">
                    <span className="meta-pill">
                      <IconMapPin size={12} />
                      <span>{location}</span>
                    </span>
                    <span className="meta-dot">·</span>
                    <span className="meta-stops">{stopCount} {stopCount === 1 ? 'stop' : 'stops'}</span>
                    <span className="meta-dot">·</span>
                    <span className="meta-cost">{costStr}</span>
                  </div>
                </div>

                <div className="library-card-footer">
                  <button
                    type="button"
                    className="btn-open-plan"
                    onClick={() => handleOpen(plan.id)}
                    disabled={isOpening}
                  >
                    <span>{isOpening ? 'Opening…' : 'Open plan'}</span>
                    <IconArrowRight size={14} />
                  </button>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
};
