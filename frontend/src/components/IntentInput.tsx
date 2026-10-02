import React, { useState, useRef, useImperativeHandle, forwardRef } from 'react';
import {
  IconArrowRight,
  IconArrowDown,
  IconNavigation,
  IconMapPin,
  IconAlertCircle,
} from './Icons';

export interface IntentInputHandle {
  focus: () => void;
  setIntent: (text: string) => void;
  reset?: () => void;
}

interface IntentInputProps {
  onSubmit: (intent: string, origin?: string, startTime?: string, transportPreference?: string) => void;
  isLoading: boolean;
  defaultValue?: string;
}

interface ExamplePrompt {
  tag: string;
  title: string;
  meta: string;
  prompt: string;
}

const EDITORIAL_PROMPTS: ExamplePrompt[] = [
  {
    tag: 'LUNCH',
    title: 'Lunch somewhere pretty in the south',
    meta: '2 people · Under R500 · Southern Suburbs',
    prompt: 'Lunch somewhere pretty in the Southern Suburbs under R500',
  },
  {
    tag: 'RELAXED',
    title: 'A relaxed Saturday with friends',
    meta: 'No rush · Good food · Easy pace',
    prompt: 'A relaxed Saturday with my friends, somewhere good to eat',
  },
  {
    tag: 'ROMANCE',
    title: 'Dinner romantic, then something fun',
    meta: '2 people · Candlelit · Then live music',
    prompt: 'Dinner somewhere romantic and then something fun',
  },
  {
    tag: 'OUTDOORS',
    title: 'A cheap afternoon outdoors',
    meta: 'Solo · Under R200 · Fresh air',
    prompt: 'A cheap afternoon outdoors',
  },
  {
    tag: 'CULTURE',
    title: 'Local culture & historic streets',
    meta: 'Solo · Craft & coffee · R250',
    prompt: 'An afternoon exploring local culture, historic streets, and craft food markets.',
  },
  {
    tag: 'RAINY',
    title: 'Sheltered day with two kids',
    meta: '4 people · Indoors only · R800',
    prompt: 'Family outing with 2 kids this Saturday, indoor activities only because of bad weather, budget R800.',
  },
];

export const IntentInput = forwardRef<IntentInputHandle, IntentInputProps>(
  ({ onSubmit, isLoading, defaultValue = '' }, ref) => {
    const [intent, setIntent] = useState(defaultValue);
    const [step, setStep] = useState<'intent' | 'decision'>('intent');
    const [originDraft, setOriginDraft] = useState('');
    const [transportChoice, setTransportChoice] = useState<string>('');
    const [dateChoice, setDateChoice] = useState<'today' | 'tomorrow' | 'custom'>('today');
    const [customDate, setCustomDate] = useState(() => new Date().toISOString().split('T')[0]);
    const [timeChoice, setTimeChoice] = useState<'morning' | 'afternoon' | 'evening' | 'custom'>('morning');
    const [customTime, setCustomTime] = useState('10:00');
    const [isLocating, setIsLocating] = useState(false);
    const [locationError, setLocationError] = useState<string | null>(null);
    const [isFocused, setIsFocused] = useState(false);
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const locationInputRef = useRef<HTMLInputElement>(null);

    useImperativeHandle(ref, () => ({
      focus: () => {
        if (step === 'intent' && textareaRef.current) {
          textareaRef.current.focus();
          textareaRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' });
        } else if (step === 'decision' && locationInputRef.current) {
          locationInputRef.current.focus();
          locationInputRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
      },
      setIntent: (text: string) => {
        setIntent(text);
        setStep('intent');
        if (textareaRef.current) {
          textareaRef.current.focus();
        }
      },
      reset: () => {
        setIntent('');
        setStep('intent');
        setOriginDraft('');
        setTransportChoice('');
        setDateChoice('today');
        setTimeChoice('morning');
        setLocationError(null);
      },
    }));

    const computeIsoStartTime = (): string => {
      const baseDate = new Date();
      if (dateChoice === 'tomorrow') {
        baseDate.setDate(baseDate.getDate() + 1);
      } else if (dateChoice === 'custom' && customDate) {
        const parts = customDate.split('-');
        if (parts.length === 3) {
          baseDate.setFullYear(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
        }
      }

      let hour = 10;
      let minute = 0;
      if (timeChoice === 'afternoon') {
        hour = 14;
      } else if (timeChoice === 'evening') {
        hour = 19;
      } else if (timeChoice === 'custom' && customTime) {
        const timeParts = customTime.split(':');
        if (timeParts.length >= 2) {
          hour = Number(timeParts[0]);
          minute = Number(timeParts[1]);
        }
      }

      baseDate.setHours(hour, minute, 0, 0);
      return baseDate.toISOString();
    };

    const handleSubmit = (e?: React.FormEvent) => {
      if (e) e.preventDefault();
      const trimmed = intent.trim();
      if (!trimmed || isLoading) return;

      setLocationError(null);
      setStep('decision');
      setTimeout(() => locationInputRef.current?.focus(), 100);
    };

    const handleFinalDraftSubmit = () => {
      const trimmedIntent = intent.trim();
      if (!trimmedIntent || isLoading) return;
      const finalOrigin = originDraft.trim() ? originDraft.trim() : undefined;
      const isoTime = computeIsoStartTime();
      onSubmit(trimmedIntent, finalOrigin, isoTime, transportChoice || undefined);
    };

    const handleDetectLocation = () => {
      if (!navigator.geolocation) {
        setLocationError('Geolocation is not supported by your browser. Please type your neighbourhood below.');
        return;
      }
      setIsLocating(true);
      setLocationError(null);
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          setIsLocating(false);
          const coords = `${pos.coords.latitude.toFixed(4)}, ${pos.coords.longitude.toFixed(4)}`;
          setOriginDraft(coords);
        },
        (err) => {
          setIsLocating(false);
          let msg = 'Could not access location. Please type your neighbourhood or suburb below.';
          if (err.code === 1) {
            msg = 'Location permission was denied. Please type your neighbourhood below.';
          }
          setLocationError(msg);
        },
        { timeout: 8000, enableHighAccuracy: true }
      );
    };

    const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSubmit();
      }
    };

    const handleSelectPrompt = (promptText: string) => {
      setIntent(promptText);
      setLocationError(null);
      setStep('decision');
      setTimeout(() => locationInputRef.current?.focus(), 100);
    };

    const handleScrollDown = () => {
      const elem = document.getElementById('how-it-works');
      elem?.scrollIntoView({ behavior: 'smooth' });
    };

    return (
      <section id="hero-input" className="hero-editorial-stage">
        <div className="hero-stage-container">
          {/* Brand Masthead */}
          <div className="hero-brand-masthead">
            <span className="masthead-name">DAYFORM</span>
            <span className="masthead-edition">EDITION 2026 · ISSUE NO. 12</span>
          </div>

          <div className="hero-headline-block">
            <p className="df-hero-question">What are we doing today?</p>

            <div className="hero-promise-callout">
              <p className="hero-promise-lead">
                Tell me what you want to do. <br />
                <span className="hero-promise-accent">I’ll figure out the rest.</span>
              </p>
            </div>
          </div>

          {/* High-Contrast Command Surface */}
          <div className={`hero-command-container df-command df-light ${isFocused ? 'focused' : ''}`}>
            {step === 'intent' ? (
              <form onSubmit={handleSubmit} className="hero-command-form">
                <div className="hero-command-box command-input-slot">
                  <label htmlFor="intent-input" className="df-sr-only">
                    Describe the day you want in your own words
                  </label>
                  <textarea
                    id="intent-input"
                    ref={textareaRef}
                    className="hero-command-textarea"
                    rows={3}
                    value={intent}
                    onChange={(e) => setIntent(e.target.value)}
                    onFocus={() => setIsFocused(true)}
                    onBlur={() => setIsFocused(false)}
                    onKeyDown={handleKeyDown}
                    placeholder="Lunch somewhere pretty in the Southern Suburbs under R500…&#10;&#10;or: a cheap afternoon outdoors"
                    disabled={isLoading}
                  />
                </div>

                <div className="hero-command-action-row command-footer-strip">
                  <span className="command-key-hint">Press ↵ Enter</span>

                  <button
                    type="submit"
                    className="hero-command-cta"
                    disabled={isLoading || !intent.trim()}
                    aria-label="Continue to plan details"
                  >
                    {isLoading ? (
                      <span className="cta-loading-state">
                        <span className="cta-spinner" />
                        <span>Reading your day…</span>
                      </span>
                    ) : (
                      <span className="cta-label-state">
                        <span>Give it shape</span>
                        <IconArrowRight size={16} className="cta-arrow" />
                      </span>
                    )}
                  </button>
                </div>
              </form>
            ) : (
              /* Pre-Draft Decision Layer */
              <div className="location-prompt-box predraft-decision-box">
                <div className="location-prompt-header">
                  <div className="location-prompt-badge">
                    <IconMapPin size={12} />
                    <span>PRE-DRAFT DECISIONS</span>
                  </div>
                  <h3 className="location-prompt-title">Shape your day</h3>
                  <p className="location-prompt-subtext">
                    Set your starting point, how you move, and when you are going.
                  </p>
                </div>

                {locationError && (
                  <div className="location-error-alert" role="alert">
                    <IconAlertCircle size={14} />
                    <span>{locationError}</span>
                  </div>
                )}

                {/* 1. Starting Location */}
                <div className="predraft-decision-block">
                  <span className="predraft-decision-label">Where are you starting?</span>
                  <div className="location-action-bar">
                    <button
                      type="button"
                      className="btn-locate-primary"
                      onClick={handleDetectLocation}
                      disabled={isLoading || isLocating}
                    >
                      {isLocating ? (
                        <>
                          <span className="cta-spinner mini" />
                          <span>Finding your location…</span>
                        </>
                      ) : (
                        <>
                          <IconNavigation size={14} />
                          <span>Use my current location</span>
                        </>
                      )}
                    </button>
                  </div>

                  <div className="location-manual-group">
                    <div className="location-manual-input-wrap">
                      <input
                        ref={locationInputRef}
                        type="text"
                        className="location-manual-input"
                        placeholder="Or enter neighbourhood (e.g. Cape Town CBD, Sea Point…)"
                        value={originDraft}
                        onChange={(e) => setOriginDraft(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') {
                            e.preventDefault();
                            handleFinalDraftSubmit();
                          }
                        }}
                        disabled={isLoading || isLocating}
                        aria-label="Where are you starting?"
                      />
                    </div>

                    <div className="location-quick-chips">
                      <span className="chips-label">Popular areas:</span>
                      <div className="chips-list">
                        {['Cape Town CBD', 'Sea Point', 'Observatory', 'Newlands', 'Gardens', 'Camps Bay'].map(
                          (suburb) => (
                            <button
                              key={suburb}
                              type="button"
                              className={`suggestion-chip${originDraft === suburb ? ' is-active' : ''}`}
                              onClick={() => setOriginDraft(suburb)}
                              disabled={isLoading || isLocating}
                            >
                              {suburb}
                            </button>
                          )
                        )}
                      </div>
                    </div>
                  </div>
                </div>

                {/* 2. Getting Around (Transport Preference) */}
                <div className="predraft-decision-block">
                  <span className="predraft-decision-label">How are you getting around?</span>
                  <div className="transport-preference-options" role="group" aria-label="Transport choice">
                    <button
                      type="button"
                      className={`transport-preference-chip${transportChoice === '' ? ' is-active' : ''}`}
                      onClick={() => setTransportChoice('')}
                    >
                      Any
                    </button>
                    <button
                      type="button"
                      className={`transport-preference-chip${transportChoice === 'walking' ? ' is-active' : ''}`}
                      onClick={() => setTransportChoice('walking')}
                    >
                      Walk
                    </button>
                    <button
                      type="button"
                      className={`transport-preference-chip${transportChoice === 'transit' ? ' is-active' : ''}`}
                      onClick={() => setTransportChoice('transit')}
                    >
                      Public transport
                    </button>
                    <button
                      type="button"
                      className={`transport-preference-chip${transportChoice === 'uber' ? ' is-active' : ''}`}
                      onClick={() => setTransportChoice('uber')}
                    >
                      Ride-hailing
                    </button>
                  </div>
                </div>

                {/* 3. When Are You Going? */}
                <div className="predraft-decision-block">
                  <span className="predraft-decision-label">When are you going?</span>
                  <div className="when-decision-grid">
                    {/* Date choice */}
                    <div className="when-choice-row" role="group" aria-label="Day choice">
                      <button
                        type="button"
                        className={`transport-preference-chip${dateChoice === 'today' ? ' is-active' : ''}`}
                        onClick={() => setDateChoice('today')}
                      >
                        Today
                      </button>
                      <button
                        type="button"
                        className={`transport-preference-chip${dateChoice === 'tomorrow' ? ' is-active' : ''}`}
                        onClick={() => setDateChoice('tomorrow')}
                      >
                        Tomorrow
                      </button>
                      <button
                        type="button"
                        className={`transport-preference-chip${dateChoice === 'custom' ? ' is-active' : ''}`}
                        onClick={() => setDateChoice('custom')}
                      >
                        Pick a date
                      </button>
                      {dateChoice === 'custom' && (
                        <input
                          type="date"
                          className="native-datetime-input"
                          value={customDate}
                          min={new Date().toISOString().split('T')[0]}
                          onChange={(e) => setCustomDate(e.target.value)}
                          aria-label="Pick custom date"
                        />
                      )}
                    </div>

                    {/* Time choice */}
                    <div className="when-choice-row" role="group" aria-label="Time of day choice">
                      <button
                        type="button"
                        className={`transport-preference-chip${timeChoice === 'morning' ? ' is-active' : ''}`}
                        onClick={() => setTimeChoice('morning')}
                      >
                        Morning
                      </button>
                      <button
                        type="button"
                        className={`transport-preference-chip${timeChoice === 'afternoon' ? ' is-active' : ''}`}
                        onClick={() => setTimeChoice('afternoon')}
                      >
                        Afternoon
                      </button>
                      <button
                        type="button"
                        className={`transport-preference-chip${timeChoice === 'evening' ? ' is-active' : ''}`}
                        onClick={() => setTimeChoice('evening')}
                      >
                        Evening
                      </button>
                      <button
                        type="button"
                        className={`transport-preference-chip${timeChoice === 'custom' ? ' is-active' : ''}`}
                        onClick={() => setTimeChoice('custom')}
                      >
                        Pick a time
                      </button>
                      {timeChoice === 'custom' && (
                        <input
                          type="time"
                          className="native-datetime-input"
                          value={customTime}
                          onChange={(e) => setCustomTime(e.target.value)}
                          aria-label="Pick custom time"
                        />
                      )}
                    </div>
                  </div>
                </div>

                <div className="location-prompt-footer">
                  <button
                    type="button"
                    className="btn-location-back"
                    onClick={() => setStep('intent')}
                    disabled={isLoading}
                  >
                    ← Edit intention
                  </button>

                  <button
                    type="button"
                    className="hero-command-cta draft-my-day-cta"
                    disabled={isLoading}
                    onClick={handleFinalDraftSubmit}
                  >
                    {isLoading ? (
                      <span className="cta-loading-state">
                        <span className="cta-spinner" />
                        <span>Drafting your day…</span>
                      </span>
                    ) : (
                      <span className="cta-label-state">
                        <span>Draft my day</span>
                        <IconArrowRight size={16} className="cta-arrow" />
                      </span>
                    )}
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* Discovery & Plan Ideas Matrix Grid */}
          <div className="hero-curated-prompts">
            <div className="curated-prompts-header">
              <span className="prompts-kicker">Not sure? Start from one of these</span>
              <span className="prompts-hint">Plain words are fine — Dayform reads between them</span>
            </div>

            <div className="discovery-matrix-grid">
              {EDITORIAL_PROMPTS.map((item) => {
                const isSelected = intent === item.prompt;
                return (
                  <button
                    key={item.title}
                    type="button"
                    className={`discovery-matrix-cell ${isSelected ? 'active' : ''}`}
                    onClick={() => handleSelectPrompt(item.prompt)}
                    disabled={isLoading}
                  >
                    <div className="discovery-cell-top">
                      <span className="discovery-cell-tag">{item.tag}</span>
                      <span className="discovery-cell-cue">Use idea ↗</span>
                    </div>
                    <h3 className="discovery-cell-title">{item.title}</h3>
                    <p className="discovery-cell-meta">{item.meta}</p>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Scroll Cue to Engine Mechanics */}
          <button
            type="button"
            className="hero-scroll-invite hero-scroll-trigger"
            onClick={handleScrollDown}
            aria-label="Scroll to how it works"
          >
            <span className="invite-label scroll-label">HOW THE ENGINE THINKS</span>
            <IconArrowDown size={14} className="invite-arrow-icon scroll-icon" />
          </button>
        </div>
      </section>
    );
  }
);

IntentInput.displayName = 'IntentInput';
