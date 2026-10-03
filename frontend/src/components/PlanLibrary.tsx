import React, { useEffect, useState } from 'react';
import type { PlanRead } from '../types/planning';
import { listPlans, updatePlan, deletePlan } from '../api/planning';
import {
  IconCalendar,
  IconClock,
  IconArrowRight,
  IconPlus,
  IconMapPin,
  IconCheck,
  IconAlertCircle,
  IconMoreVertical,
  IconEdit,
  IconTrash,
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

  // Overflow action menu state
  const [activeMenuPlanId, setActiveMenuPlanId] = useState<string | null>(null);

  // Edit / Rename state
  const [editingPlanId, setEditingPlanId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const [isSavingTitle, setIsSavingTitle] = useState(false);

  // Delete confirmation state
  const [confirmDeletePlanId, setConfirmDeletePlanId] = useState<string | null>(null);
  const [isDeletingPlanId, setIsDeletingPlanId] = useState<string | null>(null);

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

  // Listen for clicks outside open menu or Escape key
  useEffect(() => {
    const handleDocumentClick = (e: MouseEvent) => {
      const target = e.target as HTMLElement | null;
      if (!target?.closest('.library-card-actions-wrapper')) {
        setActiveMenuPlanId(null);
      }
    };
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setActiveMenuPlanId(null);
        if (confirmDeletePlanId) setConfirmDeletePlanId(null);
      }
    };
    document.addEventListener('click', handleDocumentClick);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('click', handleDocumentClick);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [confirmDeletePlanId]);

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

  const handleStartRename = (plan: PlanRead) => {
    setActiveMenuPlanId(null);
    setConfirmDeletePlanId(null);
    setEditingPlanId(plan.id);
    setEditTitle(plan.title || plan.intention || '');
  };

  const handleCancelRename = () => {
    setEditingPlanId(null);
    setEditTitle('');
  };

  const handleSaveRename = async (planId: string) => {
    const trimmed = editTitle.trim();
    if (!trimmed) return;
    setIsSavingTitle(true);
    setError(null);
    try {
      const updated = await updatePlan(planId, { title: trimmed });
      setPlans((prev) =>
        prev.map((p) => (p.id === planId ? { ...p, title: updated.title || trimmed } : p))
      );
      setEditingPlanId(null);
      setEditTitle('');
    } catch (err) {
      console.error('Failed to rename plan:', err);
      setError('Could not rename plan. Please try again.');
    } finally {
      setIsSavingTitle(false);
    }
  };

  const handleStartDelete = (planId: string) => {
    setActiveMenuPlanId(null);
    setEditingPlanId(null);
    setConfirmDeletePlanId(planId);
  };

  const handleCancelDelete = () => {
    setConfirmDeletePlanId(null);
  };

  const handleConfirmDelete = async (planId: string) => {
    setIsDeletingPlanId(planId);
    setError(null);
    try {
      await deletePlan(planId);
      // Cleanly remove from library state without page reload
      setPlans((prev) => prev.filter((p) => p.id !== planId));
      setConfirmDeletePlanId(null);
    } catch (err) {
      console.error('Failed to delete plan:', err);
      setError('Could not delete plan. Please try again.');
    } finally {
      setIsDeletingPlanId(null);
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
            const isEditing = editingPlanId === plan.id;
            const isConfirmingDelete = confirmDeletePlanId === plan.id;
            const isDeleting = isDeletingPlanId === plan.id;

            return (
              <article
                key={plan.id}
                className={`library-card${isConfirmingDelete ? ' is-confirming-delete' : ''}`}
              >
                <div className="library-card-body">
                  <div className="library-card-top">
                    <div className="library-card-badges">
                      <span className="library-status-badge">
                        <IconCheck size={11} />
                        <span>{plan.status === 'ready' ? 'Ready' : 'Saved'}</span>
                      </span>
                      <span className="library-date-badge">
                        <IconClock size={12} />
                        <span>{dateStr}</span>
                      </span>
                    </div>

                    {/* Restrained card overflow action */}
                    <div className="library-card-actions-wrapper">
                      <button
                        type="button"
                        className="btn-card-overflow"
                        onClick={(e) => {
                          e.stopPropagation();
                          setActiveMenuPlanId(activeMenuPlanId === plan.id ? null : plan.id);
                        }}
                        aria-label={`Options for ${title}`}
                        aria-haspopup="true"
                        aria-expanded={activeMenuPlanId === plan.id}
                        disabled={isOpening || isDeleting}
                      >
                        <IconMoreVertical size={16} />
                      </button>

                      {activeMenuPlanId === plan.id && (
                        <div className="card-overflow-menu" role="menu">
                          <button
                            type="button"
                            className="card-menu-item"
                            role="menuitem"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleStartRename(plan);
                            }}
                          >
                            <IconEdit size={13} />
                            <span>Rename</span>
                          </button>
                          <button
                            type="button"
                            className="card-menu-item is-danger"
                            role="menuitem"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleStartDelete(plan.id);
                            }}
                          >
                            <IconTrash size={13} />
                            <span>Delete</span>
                          </button>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Title or Inline Edit Form */}
                  {isEditing ? (
                    <form
                      className="library-card-rename-form"
                      onSubmit={(e) => {
                        e.preventDefault();
                        handleSaveRename(plan.id);
                      }}
                    >
                      <input
                        type="text"
                        className="library-rename-input"
                        value={editTitle}
                        onChange={(e) => setEditTitle(e.target.value)}
                        maxLength={255}
                        autoFocus
                        placeholder="Plan title"
                        disabled={isSavingTitle}
                        onKeyDown={(e) => {
                          if (e.key === 'Escape') handleCancelRename();
                        }}
                        aria-label="Rename plan title"
                      />
                      <div className="library-rename-actions">
                        <button
                          type="submit"
                          className="btn-rename-save"
                          disabled={isSavingTitle || !editTitle.trim()}
                        >
                          {isSavingTitle ? 'Saving…' : 'Save'}
                        </button>
                        <button
                          type="button"
                          className="btn-rename-cancel"
                          disabled={isSavingTitle}
                          onClick={handleCancelRename}
                        >
                          Cancel
                        </button>
                      </div>
                    </form>
                  ) : (
                    <h3 className="library-card-title">{title}</h3>
                  )}

                  {/* Confirmation banner when deleting this card */}
                  {isConfirmingDelete && (
                    <div className="library-card-delete-prompt" role="alert">
                      <p className="delete-prompt-message">
                        <strong>Delete this plan?</strong> This cannot be undone.
                      </p>
                      <div className="delete-prompt-actions">
                        <button
                          type="button"
                          className="btn-delete-confirm"
                          onClick={() => handleConfirmDelete(plan.id)}
                          disabled={isDeleting}
                        >
                          {isDeleting ? 'Deleting…' : 'Delete'}
                        </button>
                        <button
                          type="button"
                          className="btn-delete-cancel"
                          disabled={isDeleting}
                          onClick={handleCancelDelete}
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  )}

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
                    disabled={isOpening || isDeleting || isConfirmingDelete}
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
