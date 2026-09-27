from __future__ import annotations

import re
from decimal import Decimal
from uuid import UUID

from app.application.planning.ports import PlanningUnderstandingPort
from app.domain.entities.planning.constraints import BudgetConstraint, BudgetStyle, TemporalConstraint
from app.domain.entities.planning.information import InformationCategory
from app.domain.entities.planning.understanding import BudgetKind, PlanningUnderstanding, ProvenanceKind


class DeterministicUnderstandingEngine(PlanningUnderstandingPort):
    """Deterministic, provider-agnostic implementation of PlanningUnderstandingPort.

    Implements a multi-stage conversational understanding pipeline that normalizes the request,
    extracts intent, occasion, people/relationship context, date and time windows, location semantics,
    budget semantics, preferences, exclusions, and activity categories without guessing or inventing facts.
    """

    async def understand(self, user_id: UUID, raw_request: str) -> PlanningUnderstanding:
        return self.parse(raw_request)

    def parse(self, raw_request: str) -> PlanningUnderstanding:
        request = raw_request.strip()
        if not request:
            raise ValueError("Planning request cannot be empty.")

        normalized = self._normalize(request)
        provenance: dict[str, str] = {}
        ambiguities: list[str] = []

        # 1. Occasion & relationship context
        occasion, occasion_prov = self._extract_occasion(normalized)
        if occasion:
            provenance["occasion"] = occasion_prov.value
        else:
            provenance["occasion"] = ProvenanceKind.UNKNOWN.value

        # 2. People & group context
        people_count, rel_context, people_prov, people_ambiguities = self._extract_people(normalized, occasion)
        ambiguities.extend(people_ambiguities)
        if people_count is not None:
            provenance["people_count"] = people_prov.value
        else:
            provenance["people_count"] = ProvenanceKind.UNKNOWN.value
        if rel_context:
            provenance["relationship_context"] = people_prov.value

        # 3. Date & time windows
        (
            date_spec,
            time_window,
            start_time,
            end_time,
            deadline,
            time_confidence,
            duration_limit,
            date_prov,
            time_prov,
            time_ambiguities,
        ) = self._extract_date_and_time(normalized)
        ambiguities.extend(time_ambiguities)
        if date_spec:
            provenance["date"] = date_prov.value
        else:
            provenance["date"] = ProvenanceKind.UNKNOWN.value
        if time_window:
            provenance["time_window"] = time_prov.value
        else:
            provenance["time_window"] = ProvenanceKind.UNKNOWN.value
        if start_time:
            provenance["start_time"] = time_prov.value
        if end_time:
            provenance["end_time"] = time_prov.value
        if duration_limit:
            provenance["duration_limit"] = ProvenanceKind.EXPLICIT.value

        # 4. Location semantics
        location, is_inferred, loc_prov, location_descriptors = self._extract_location(normalized)
        provenance["location"] = loc_prov.value

        # 4b. Mobility preference (how the user intends to move between stops)
        transport_mode = self._extract_transport_mode(normalized)
        provenance["transport_mode"] = (
            ProvenanceKind.EXPLICIT.value if transport_mode else ProvenanceKind.UNKNOWN.value
        )

        # 5. Budget semantics
        budget_amount, budget_kind, budget_prov, budget_model = self._extract_budget(normalized)
        provenance["budget"] = budget_prov.value

        # 6. Exclusions (hard negative constraints)
        exclusions = self._extract_exclusions(normalized)
        if exclusions:
            provenance["exclusions"] = ProvenanceKind.EXPLICIT.value

        # 7. Setting & weather context
        setting_pref, weather_ctx = self._extract_setting_and_weather(normalized)

        # 8. Soft preferences
        preferences = self._extract_preferences(normalized, exclusions)
        if preferences:
            provenance["preferences"] = ProvenanceKind.EXPLICIT.value

        # 9. Semantic descriptors (open-ended vibes, aesthetics, activities)
        semantic_descriptors = self._extract_semantic_descriptors(normalized, location_descriptors)

        # 10. Activity categories
        activity_types = self._extract_activity_types(normalized, occasion, preferences)
        if activity_types:
            provenance["activity_types"] = ProvenanceKind.INFERRED.value

        # 11. Goal synthesis
        goal = self._extract_goal(normalized, occasion, rel_context)

        day_of_week = (
            date_spec if date_spec in {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"} else None
        )
        temporal_model = TemporalConstraint(
            date_spec=date_spec,
            day_of_week=day_of_week,
            start_time=start_time,
            end_time=end_time,
            deadline=deadline,
            time_window=time_window,
            duration_limit_minutes=duration_limit,
            confidence=time_confidence,
        )

        return PlanningUnderstanding(
            raw_request=request,
            goal=goal,
            occasion=occasion,
            people_count=people_count,
            relationship_context=rel_context,
            date_spec=date_spec,
            time_window=time_window,
            start_time=start_time,
            end_time=end_time,
            deadline=deadline,
            time_confidence=time_confidence,
            duration_limit_minutes=duration_limit,
            location=location,
            location_is_inferred=is_inferred,
            transport_mode=transport_mode,
            budget_amount=budget_amount,
            budget_kind=budget_kind,
            budget_model=budget_model,
            temporal_model=temporal_model,
            preferences=tuple(preferences),
            exclusions=tuple(exclusions),
            activity_types=tuple(activity_types),
            semantic_descriptors=tuple(semantic_descriptors),
            setting_preference=setting_pref,
            weather_context=weather_ctx,
            ambiguities=tuple(ambiguities),
            provenance=provenance,
        )

    @staticmethod
    def _normalize(text: str) -> str:
        # Standardize quotes, hyphens, and whitespace
        normalized = text.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
        return " ".join(normalized.split())

    @staticmethod
    def _extract_occasion(text: str) -> tuple[str | None, ProvenanceKind]:
        lower = text.lower()
        if re.search(r"\b(?:date night|romantic|anniversary|on a date|for a date|cheap date|cute date|dinner date|a date|good date)\b", lower):
            return "date", ProvenanceKind.EXPLICIT
        if re.search(r"\b(?:take|taking|with|for)\s+my\s+(?:boyfriend|girlfriend|partner|husband|wife)\b", lower):
            return "date", ProvenanceKind.INFERRED
        if re.search(r"\b(?:birthday|bday|b-day)\b", lower):
            return "birthday", ProvenanceKind.EXPLICIT
        if re.search(r"\b(?:celebration|celebrate|promotion|milestone|party)\b", lower):
            return "celebration", ProvenanceKind.EXPLICIT
        if re.search(r"\b(?:girls'? day|girls'? night|boys'? night|(?:with|and)\s+(?:my |\d+\s+)?(?:friends|mates)|\b\d+\s+friends\b|\bfriends\b|my friend)\b", lower):
            return "friends", ProvenanceKind.EXPLICIT
        if re.search(r"\b(?:family|with the kids|with parents|for my mom|with my mom|for my dad|with my dad)\b", lower):
            return "family", ProvenanceKind.EXPLICIT
        if re.search(r"\b(?:just me|solo|by myself|alone|self[ -]?care)\b", lower):
            return "solo", ProvenanceKind.EXPLICIT
        if re.search(r"\b(?:hangout|hang out|casual catchup|catch up)\b", lower):
            return "casual_hangout", ProvenanceKind.EXPLICIT
        return None, ProvenanceKind.UNKNOWN

    @staticmethod
    def _extract_people(
        text: str, occasion: str | None
    ) -> tuple[int | None, str | None, ProvenanceKind, list[str]]:
        lower = text.lower()
        ambiguities: list[str] = []

        # Check for relationship mention
        rel: str | None = None
        match_partner = re.search(r"\b(?:take|taking|with|for)\s+my\s+(boyfriend|girlfriend|partner|husband|wife)\b", lower)
        if match_partner:
            rel = match_partner.group(1)

        match_family_rel = re.search(r"\b(?:(?:for|with)\s+my|my)\s+(mom|mother|dad|father|sister|brother)(?:'s|\b)", lower)
        if match_family_rel:
            rel = match_family_rel.group(1)

        word_to_num = {
            "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
            "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
        }

        # 1. "me and N friends" / "with N friends" -> N + 1
        match_friends_count = re.search(r"\b(?:me and|with)\s+(\d+)\s+friends?\b", lower)
        if match_friends_count:
            return int(match_friends_count.group(1)) + 1, "friends", ProvenanceKind.EXPLICIT, ambiguities

        # 2. Conversational "N of us" / "the N of us" (e.g. "three of us", "four of us")
        match_of_us = re.search(
            r"\b(?:(?:the\s+)?(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+of\s+us)\b",
            lower,
        )
        if match_of_us:
            raw_cnt = match_of_us.group(1)
            parsed_count = word_to_num.get(raw_cnt, int(raw_cnt) if raw_cnt.isdigit() else None)
            if parsed_count is not None:
                return parsed_count, rel or "group", ProvenanceKind.EXPLICIT, ambiguities

        # 3. Explicit people counts: "maybe 3 people", "about 4 people", "for 5 people", "for four people"
        match_people_count = re.search(
            r"\b(?:(?:maybe|around|about|for)\s+)?(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:people|persons?|guests?)\b",
            lower,
        )
        if match_people_count:
            raw_cnt = match_people_count.group(1)
            parsed_count = word_to_num.get(raw_cnt, int(raw_cnt) if raw_cnt.isdigit() else None)
            if parsed_count is not None:
                return parsed_count, rel or "group", ProvenanceKind.EXPLICIT, ambiguities

        # 4. group of N
        group_of = re.search(r"\bgroup\s+of\s+(\d+)\b", lower)
        if group_of:
            return int(group_of.group(1)), rel or "group", ProvenanceKind.EXPLICIT, ambiguities

        # 5. Conversational "for N" (e.g. "dinner for 4", "lunch for two", "for 6")
        match_for_num = re.search(
            r"\bfor\s+(\d+|one|two|three|four|five|six|seven|eight|nine|ten)(?!\s*(?:hours?|hrs?|r|rand|bucks|am|pm|days?))\b",
            lower,
        )
        if match_for_num:
            raw_cnt = match_for_num.group(1)
            parsed_count = word_to_num.get(raw_cnt, int(raw_cnt) if raw_cnt.isdigit() else None)
            if parsed_count is not None:
                return parsed_count, rel or ("couple" if parsed_count == 2 and occasion == "date" else "group"), ProvenanceKind.EXPLICIT, ambiguities

        # 6. Family with kids: "family with 2 kids" -> 2 adults + 2 kids = 4
        match_fam_kids = re.search(r"\bfamily\s+with\s+(\d+|one|two|three|four)\s+kids?\b", lower)
        if match_fam_kids:
            k_raw = match_fam_kids.group(1)
            k_cnt = word_to_num.get(k_raw, int(k_raw) if k_raw.isdigit() else 2) or 2
            return 2 + k_cnt, "family", ProvenanceKind.EXPLICIT, ambiguities

        # 7. Explicit pair / couple / friend visiting references
        if re.search(r"\b(?:neither of us|both of us|the two of us|the 2 of us)\b", lower):
            return 2, "couple" if occasion == "date" else ("friends" if "friend" in lower else "pair"), ProvenanceKind.EXPLICIT, ambiguities

        if re.search(r"\b(?:my friend is visiting|friend is visiting|visiting cape town.*we)\b", lower):
            return 2, "friends", ProvenanceKind.EXPLICIT, ambiguities

        if re.search(r"\bmy friend\b.*\bwe\b", lower) or re.search(r"\b(?:with a friend|and a friend)\b", lower):
            return 2, "friends", ProvenanceKind.EXPLICIT, ambiguities

        if re.search(r"\b(?:me and my (?:boyfriend|girlfriend|partner|husband|wife|friend))\b", lower):
            pair_rel = "boyfriend" if "boyfriend" in lower else "partner"
            if "girlfriend" in lower:
                pair_rel = "girlfriend"
            elif "friend" in lower:
                pair_rel = "friends"
            return 2, pair_rel, ProvenanceKind.EXPLICIT, ambiguities

        if re.search(r"\b(?:for two|for 2)\b", lower):
            return 2, "couple" if occasion == "date" else "pair", ProvenanceKind.EXPLICIT, ambiguities

        # 8. Partner or family inferred pair (default to 2 if no explicit count given)
        if match_partner:
            return 2, rel, ProvenanceKind.INFERRED, ambiguities

        if match_family_rel:
            return 2, rel, ProvenanceKind.INFERRED, ambiguities

        # 9. Solo
        if re.search(r"\b(?:just me|solo|by myself|alone)\b", lower):
            return 1, "solo", ProvenanceKind.EXPLICIT, ambiguities

        # 10. "with my friends" / "with friends" without a count
        if re.search(r"\b(?:with my friends|with friends|with mates)\b", lower):
            ambiguities.append("Exact group size not specified ('with friends'); planning with flexible group options.")
            return None, "friends", ProvenanceKind.EXPLICIT, ambiguities

        # Default fallback if occasion is date
        if occasion == "date":
            return 2, "couple", ProvenanceKind.INFERRED, ambiguities

        ambiguities.append("Group size not specified; defaulting to single or flexible group options.")
        return None, None, ProvenanceKind.UNKNOWN, ambiguities

    @staticmethod
    def _normalize_clock_time(time_val: str, meridiem: str | None = None, is_deadline: bool = False, is_evening: bool = False) -> str:
        if ":" in time_val:
            parts = time_val.split(":")
            h, m = int(parts[0]), int(parts[1])
        else:
            h, m = int(time_val), 0

        if meridiem == "pm" and h < 12:
            h += 12
        elif meridiem == "am" and h == 12:
            h = 0
        elif meridiem is None:
            if is_deadline:
                if 1 <= h <= 11:
                    h += 12
            elif is_evening:
                if 1 <= h <= 11:
                    h += 12
            else:
                if 1 <= h <= 6:
                    h += 12

        return f"{h:02d}:{m:02d}"

    @staticmethod
    def _extract_date_and_time(
        text: str,
    ) -> tuple[
        str | None,
        str | None,
        str | None,
        str | None,
        str | None,
        str,
        int | None,
        ProvenanceKind,
        ProvenanceKind,
        list[str],
    ]:
        lower = text.lower()
        ambiguities: list[str] = []

        date_spec: str | None = None
        time_window: str | None = None
        start_time: str | None = None
        end_time: str | None = None
        deadline: str | None = None
        time_confidence = "unknown"
        duration_limit_minutes: int | None = None
        date_prov = ProvenanceKind.UNKNOWN
        time_prov = ProvenanceKind.UNKNOWN
        is_evening_ctx = bool(re.search(r"\b(?:dinner|evening|night|tonight|after work)\b", lower))

        # 1. Days of week / relative dates
        for day in ("saturday", "sunday", "friday", "thursday", "wednesday", "tuesday", "monday"):
            if re.search(rf"\b{day}\b", lower):
                date_spec = day.capitalize()
                date_prov = ProvenanceKind.EXPLICIT
                break

        if not date_spec:
            if re.search(r"\bthis weekend|the weekend\b", lower):
                date_spec = "This weekend"
                date_prov = ProvenanceKind.EXPLICIT
            elif re.search(r"\bnext weekend\b", lower):
                date_spec = "Next weekend"
                date_prov = ProvenanceKind.EXPLICIT
            elif re.search(r"\btomorrow\b", lower):
                date_spec = "Tomorrow"
                date_prov = ProvenanceKind.EXPLICIT
            elif re.search(r"\btoday|tonight\b", lower):
                date_spec = "Today"
                date_prov = ProvenanceKind.EXPLICIT

        # 2. Duration limit
        num_map = {
            "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
            "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6,
        }
        m_dur = re.search(r"\b(?:only have|have|for|in)\s+(\d+|one|two|three|four|five|six)\s+hours?\b", lower)
        if not m_dur:
            m_dur = re.search(r"\b(\d+|one|two|three|four|five|six)\s+hours?\b", lower)
        if m_dur:
            dur_val = m_dur.group(1).lower()
            hours_count = num_map.get(dur_val) or (int(dur_val) if dur_val.isdigit() else None)
            if hours_count:
                duration_limit_minutes = hours_count * 60
                ambiguities.append(f"Itinerary time constraint: limited to approximately {hours_count} hours.")
        elif re.search(r"\b(?:whole afternoon|all afternoon)\b", lower):
            duration_limit_minutes = 240

        # 3. Time spans and start/end clock times
        m_span = re.search(
            r"\bfrom\s+(\d{1,2}(?::\d{2})?)\s*(am|pm)?\s+to\s+(\d{1,2}(?::\d{2})?)\s*(am|pm)?\b",
            lower,
        )
        if m_span:
            start_time = DeterministicUnderstandingEngine._normalize_clock_time(m_span.group(1), m_span.group(2), is_evening=is_evening_ctx)
            end_time = DeterministicUnderstandingEngine._normalize_clock_time(m_span.group(3), m_span.group(4), is_deadline=True, is_evening=is_evening_ctx)
            deadline = end_time
            time_confidence = "exact"
            time_prov = ProvenanceKind.EXPLICIT
            time_window = f"{start_time}-{end_time}"
        else:
            m_start_approx = re.search(
                r"\b(?:start\s+around|start\s+about|around|about|approx(?:imately)?)\s+(\d{1,2}(?::\d{2})?)\s*(am|pm)?\b",
                lower,
            )
            m_start_exact = re.search(r"\b(?:start\s+at|at)\s+(\d{1,2}(?::\d{2})?)\s*(am|pm)?\b", lower)
            m_start_after = re.search(r"\b(?:after|from)\s+(\d{1,2}(?::\d{2})?)\s*(am|pm)?\b", lower)

            if m_start_approx:
                start_time = DeterministicUnderstandingEngine._normalize_clock_time(m_start_approx.group(1), m_start_approx.group(2), is_evening=is_evening_ctx)
                time_confidence = "approximate"
                time_prov = ProvenanceKind.EXPLICIT
                ambiguities.append(f"Start time is approximate (~{start_time}); scheduled with flexibility.")
            elif m_start_exact:
                start_time = DeterministicUnderstandingEngine._normalize_clock_time(m_start_exact.group(1), m_start_exact.group(2), is_evening=is_evening_ctx)
                time_confidence = "exact"
                time_prov = ProvenanceKind.EXPLICIT
            elif m_start_after:
                start_time = DeterministicUnderstandingEngine._normalize_clock_time(m_start_after.group(1), m_start_after.group(2), is_evening=is_evening_ctx)
                time_confidence = "exact"
                time_prov = ProvenanceKind.EXPLICIT

            m_end = re.search(
                r"\b(?:until|to|home by|be home by|finish by|leave by|need to leave by|back by|done by|by|before)\s+(\d{1,2}(?::\d{2})?)\s*(am|pm)?\b",
                lower,
            )
            if m_end:
                end_time = DeterministicUnderstandingEngine._normalize_clock_time(m_end.group(1), m_end.group(2), is_deadline=True, is_evening=is_evening_ctx)
                deadline = end_time
                time_prov = ProvenanceKind.EXPLICIT
                ambiguities.append(f"Requested end time: home/done by {end_time}.")

        # 4. Period keywords
        period: str | None = None
        if re.search(r"\b(?:morning|breakfast)\b", lower):
            period = "morning"
        elif re.search(r"\b(?:afternoon|lunchtime|lunch)\b", lower):
            period = "afternoon"
        elif re.search(r"\b(?:evening|dinner time|dinner)\b", lower):
            period = "evening"
        elif re.search(r"\b(?:night|tonight|late night)\b", lower):
            period = "night"
        elif re.search(r"\bafter work\b", lower):
            period = "after_work"
        elif re.search(r"\ball day|whole day\b", lower):
            period = "all_day"

        if start_time and end_time:
            time_window = f"{start_time}-{end_time}"
        elif period and not start_time and not end_time:
            time_window = period
            time_confidence = "inferred"
            time_prov = ProvenanceKind.INFERRED
            if period == "morning":
                start_time = "09:00"
                end_time = "12:30"
            elif period == "afternoon":
                start_time = "12:30"
                end_time = "17:30"
            elif period == "evening":
                start_time = "18:00"
                end_time = "22:00"
            elif period == "night":
                start_time = "20:00"
                end_time = "23:30"
            elif period == "after_work":
                start_time = "17:30"
                end_time = "21:30"
            elif period == "all_day":
                start_time = "09:00"
                end_time = "20:00"
        elif period and start_time and not end_time:
            time_window = period
            if period == "morning":
                end_time = "12:30"
            elif period == "afternoon":
                end_time = "17:30"
            elif period in {"evening", "night"}:
                end_time = "22:00"
        elif period and not start_time and end_time:
            time_window = period
            if period == "evening":
                start_time = "18:00"
            elif period == "dinner":
                start_time = "19:00"
            elif period == "afternoon":
                start_time = "13:00"
        elif start_time and not time_window:
            time_window = f"from_{start_time}"

        if date_spec and not time_window and not start_time:
            ambiguities.append(f"Specific time window on {date_spec} not stated; planning for a flexible schedule.")

        return (
            date_spec,
            time_window,
            start_time,
            end_time,
            deadline,
            time_confidence,
            duration_limit_minutes,
            date_prov,
            time_prov,
            ambiguities,
        )

    @staticmethod
    def _extract_location(text: str) -> tuple[str, bool, ProvenanceKind, list[str]]:
        lower = text.lower()
        extracted_descriptors: list[str] = []

        # Explicit known neighborhoods
        neighborhood_map = {
            "sea point": "Sea Point",
            "camps bay": "Camps Bay",
            "v&a": "Waterfront",
            "waterfront": "Waterfront",
            "bo-kaap": "Bo-Kaap",
            "gardens": "Gardens",
            "kloof street": "Kloof Street",
            "bree street": "Bree Street",
            "constantia": "Constantia",
            "green point": "Green Point",
            "newlands": "Newlands",
            "woodstock": "Woodstock",
            "kalk bay": "Kalk Bay",
        }
        for token, loc_name in neighborhood_map.items():
            if re.search(rf"\b{token}\b", lower):
                return loc_name, False, ProvenanceKind.EXPLICIT, extracted_descriptors

        # Explicit mention of Cape Town
        if re.search(r"\b(?:in|near|around)\s+cape town\b", lower):
            return "Cape Town", False, ProvenanceKind.EXPLICIT, extracted_descriptors

        # Conversational / inferred city references
        if re.search(r"\b(?:around town|in town|central|somewhere central|city bowl|near town|close by)\b", lower):
            return "Cape Town", True, ProvenanceKind.INFERRED, extracted_descriptors

        # General pattern "in/near/around [Candidate]"
        match = re.search(
            r"\b(?:in|near|around)\s+([A-Za-z][A-Za-z\s-]*?)(?=\s+(?:for|with|on|this|next|around|maybe|under|budget)\b|[,.!?]|$)",
            text,
            re.IGNORECASE,
        )
        if match:
            candidate = match.group(1).strip()
            cand_lower = candidate.lower()
            is_non_geo = (
                bool(re.match(r"^(?:a|an|the)\b", cand_lower))
                or any(noun in cand_lower for noun in ("restaurant", "restaurent", "cafe", "bistro", "pub", "bar", "spot", "place", "venue", "room", "setting"))
                or any(adj in cand_lower for adj in ("quiet", "dark", "dim", "cozy", "romantic", "indoor", "outdoor", "themed"))
                or cand_lower in {"town", "a date", "the mood", "mind"}
            )
            if not is_non_geo and len(candidate) > 2:
                return candidate, False, ProvenanceKind.EXPLICIT, extracted_descriptors
            elif is_non_geo:
                # Capture the non-geographic candidate as semantic descriptors
                cleaned_desc = re.sub(r"^(?:a|an|the)\s+", "", cand_lower)
                cleaned_desc = re.sub(r"\b(?:restaurant|restaurent|cafe|bistro|pub|bar|spot|place|venue)\b", "", cleaned_desc).strip()
                if cleaned_desc:
                    extracted_descriptors.append(cleaned_desc)

        # Default context
        return "Cape Town", True, ProvenanceKind.DEFAULTED, extracted_descriptors

    @staticmethod
    def _extract_budget(text: str) -> tuple[Decimal | None, BudgetKind, ProvenanceKind, BudgetConstraint]:
        lower = text.lower()

        # Check per-person vs total markers
        is_per_person = bool(re.search(r"\b(?:each|per person|a person|per head|a head)\b", lower))
        priority_note: str | None = None
        if re.search(r"\b(?:spend most (?:of it )?on dinner|most on dinner|most of the budget on dinner)\b", lower):
            priority_note = "spend_most_on_dinner"

        # Check for flexible stretch budget: "can stretch to R700", "stretch to R700", "up to R700 if needed"
        stretch_amount: Decimal | None = None
        m_stretch = re.search(r"\b(?:stretch to|can stretch to|stretch up to)\s*(?:r|rand|bucks)?\s*(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)\b", lower)
        if m_stretch:
            stretch_amount = Decimal(m_stretch.group(1).replace(",", ""))

        # 1. Explicit numeric budget extraction (R800, R2,000, R 800, 800 rand, 800 bucks) takes precedence
        base_match = None
        for m in re.finditer(r"\bR\s?(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)\b|\b(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)\s*(?:rand|bucks)\b", text, re.IGNORECASE):
            raw_val = m.group(1) or m.group(2)
            val = Decimal(raw_val.replace(",", ""))
            if stretch_amount is not None and val == stretch_amount:
                continue
            base_match = val
            break

        if base_match is None and stretch_amount is not None:
            base_match = stretch_amount

        if base_match is not None:
            amount = base_match
            if stretch_amount is not None:
                b_model = BudgetConstraint(
                    amount=amount,
                    style=BudgetStyle.FLEXIBLE_STRETCH,
                    stretch_amount=stretch_amount,
                    per_person=is_per_person,
                    priority_note=priority_note,
                )
                return amount, BudgetKind.HARD_MAX, ProvenanceKind.EXPLICIT, b_model

            if re.search(r"\b(?:under|max|maximum|at most|up to|cap at|limit|less than)\s*(?:r|rand|bucks)?\s*[\d,]+", lower):
                b_model = BudgetConstraint(
                    amount=amount,
                    style=BudgetStyle.HARD_CEILING,
                    per_person=is_per_person,
                    priority_note=priority_note,
                )
                return amount, BudgetKind.HARD_MAX, ProvenanceKind.EXPLICIT, b_model

            if re.search(r"\b(?:maybe|around|about|roughly|approx|approx\.|~)\s*(?:r|rand|bucks)?\s*[\d,]+", lower):
                b_model = BudgetConstraint(
                    amount=amount,
                    style=BudgetStyle.APPROXIMATE,
                    per_person=is_per_person,
                    priority_note=priority_note,
                )
                return amount, BudgetKind.APPROXIMATE, ProvenanceKind.EXPLICIT, b_model

            style = BudgetStyle.PER_PERSON if is_per_person else BudgetStyle.TOTAL
            b_model = BudgetConstraint(
                amount=amount,
                style=style,
                per_person=is_per_person,
                priority_note=priority_note,
            )
            return amount, BudgetKind.APPROXIMATE, ProvenanceKind.EXPLICIT, b_model

        # 2. Free / zero cost financial check (ensuring 'free' is not referring to time: 'hours free', 'free time', 'free tomorrow')
        is_temporal_free = bool(re.search(r"\b(?:hours?\s+free|free\s+time|time\s+free|free\s+(?:tomorrow|tonight|today|this|saturday|sunday|friday|morning|afternoon|evening)|(?:are|we're|i'm|i\s+am)\s+free)\b", lower))
        if not is_temporal_free:
            if re.search(r"\b(?:free of charge|zero cost|no cost|no money|no budget|zero budget|for free|cost nothing)\b", lower):
                b_model = BudgetConstraint(amount=Decimal("0"), style=BudgetStyle.HARD_CEILING)
                return Decimal("0"), BudgetKind.HARD_MAX, ProvenanceKind.EXPLICIT, b_model
            if re.search(r"\bfree\b", lower) and not re.search(r"\b(?:smoke|sugar|gluten|care|duty|hands)[ -]free\b", lower):
                b_model = BudgetConstraint(amount=Decimal("0"), style=BudgetStyle.HARD_CEILING)
                return Decimal("0"), BudgetKind.HARD_MAX, ProvenanceKind.EXPLICIT, b_model

        # 3. Qualitative budget preference without exact number
        if re.search(r"\b(?:cheap|affordable|budget[ -]friendly|on a budget|not expensive|not too expensive|nothing too expensive|nothing expensive|keep it cheap)\b", lower):
            b_model = BudgetConstraint(amount=None, style=BudgetStyle.PRIORITY_CHEAP, priority_note=priority_note)
            return None, BudgetKind.PREFERENCE, ProvenanceKind.EXPLICIT, b_model

        b_model = BudgetConstraint(amount=None, style=BudgetStyle.NONE)
        return None, BudgetKind.NONE, ProvenanceKind.UNKNOWN, b_model

    @staticmethod
    def _extract_exclusions(text: str) -> list[str]:
        lower = text.lower()
        exclusions: list[str] = []

        if re.search(r"\b(?:nothing too fancy|not too fancy|nothing fancy|not fancy|don't want anything fancy|no fancy)\b", lower):
            exclusions.append("not_too_fancy")

        # Alcohol exclusions
        if re.search(r"\b(?:doesn't drink|don't drink|does not drink|do not drink|neither of us drinks|none of us drinks|no alcohol|non[ -]alcoholic|sober|no booze|no wine|no beer)\b", lower):
            exclusions.append("no_alcohol")

        # Outdoor exclusions (explicit or weather-driven)
        if re.search(r"\b(?:no outdoor|no outdoors|nothing outdoors|not outdoors|avoid outdoors|no nature|indoors?|inside|rain|raining|rainy|sheltered|bad weather|don't want to get wet|don't want to be outside|not outside)\b", lower):
            exclusions.append("no_outdoors")

        # Nightlife & loud venue exclusions
        if re.search(r"\b(?:no clubs|no clubbing|no nightlife|no party|no parties|except clubs)\b", lower):
            exclusions.append("no_clubs")

        if re.search(r"\b(?:except loud bars|no loud bars|no loud music|no noisy places|avoid loud)\b", lower):
            exclusions.append("no_loud_bars")
            exclusions.append("no_clubs")

        if re.search(r"\b(?:not too expensive|nothing expensive|no expensive places|not ridiculously expensive)\b", lower):
            exclusions.append("nothing_expensive")

        if re.search(r"\b(?:no walking|minimal walking|avoid walking)\b", lower):
            exclusions.append("minimal_walking")

        return exclusions

    @staticmethod
    def _extract_setting_and_weather(text: str) -> tuple[str | None, str | None]:
        lower = text.lower()
        setting: str | None = None
        weather: str | None = None

        if re.search(r"\b(?:indoors?|inside|sheltered|bad weather|rain|raining|rainy|stay dry|don't want to get wet|don't want to be outside|not outside)\b", lower):
            setting = "indoor"
        elif re.search(r"\b(?:outdoors?|outside|in the sun|open air|sunny)\b", lower):
            setting = "outdoor"

        if re.search(r"\b(?:raining|rainy|rain|bad weather|storm|stormy|wet)\b", lower):
            weather = "raining"
        elif re.search(r"\b(?:sunny|sunshine|clear skies|good weather)\b", lower):
            weather = "sunny"

        return setting, weather

    @staticmethod
    def _extract_semantic_descriptors(text: str, extra_descriptors: list[str]) -> list[str]:
        lower = text.lower()
        descriptors: list[str] = list(extra_descriptors)

        patterns = [
            (r"\b(?:quiet|peaceful|calm)\b", "quiet"),
            (r"\b(?:dark themed|dark-themed|dimly lit|moody)\b", "dark themed"),
            (r"\b(?:dress up|dressing up)\b", "dress up"),
            (r"\b(?:take photos|take pictures|photoshoot|photogenic|instagrammable)\b", "take photos"),
            (r"\b(?:coffee|specialty coffee|roastery|cafe)\b", "coffee"),
            (r"\b(?:reading|read|study|bookstore|books)\b", "reading"),
            (r"\b(?:romantic|candlelit|intimate)\b", "romantic"),
            (r"\b(?:scenic|panoramic|views)\b", "scenic"),
            (r"\b(?:kids|family friendly|children)\b", "family friendly"),
            (r"\b(?:games|board games|arcade|entertainment)\b", "games"),
            (r"\b(?:culture|museum|art gallery|heritage)\b", "culture"),
            (r"\b(?:tasting|wine tasting|food tasting)\b", "tasting"),
            (r"\b(?:fancy|fine dining|upscale|luxury)\b", "fancy"),
            (r"\b(?:pretty|aesthetic|cute)\b", "pretty"),
            (r"\b(?:doesn't feel cheap|quality)\b", "quality"),
            (r"\b(?:bored|fun)\b", "fun"),
        ]
        for pattern, label in patterns:
            if re.search(pattern, lower) and label not in descriptors:
                descriptors.append(label)

        return descriptors

    @staticmethod
    def _extract_transport_mode(text: str) -> str | None:
        """Extract an explicitly stated mobility preference.

        Only explicit statements produce a value — a missing preference must stay
        unknown so mobility-aware planning can fall back to sensible defaults rather
        than inventing a transport constraint the user never gave.
        """
        lower = text.lower()
        if re.search(
            r"\b(?:public\s+transport|public\s+transit|public\s+transporation|by\s+bus|by\s+train|"
            r"take\s+the\s+(?:bus|train|taxi)|the\s+(?:bus|train|taxi|uber|bolt|metrorail)|"
            r"using\s+(?:the\s+)?(?:bus|train|taxi|uber|bolt|metrorail)|"
            r"no\s+car|without\s+a\s+car|don'?t\s+have\s+a\s+car|no\s+uber|without\s+uber|"
            r"walk(?:ing)?\s+(?:there|to\s+get\s+there|instead)|on\s+foot|shuttle)\b",
            lower,
        ):
            if re.search(
                r"\b(?:no\s+car|without\s+a\s+car|don'?t\s+have\s+a\s+car|walk(?:ing)?\s+"
                r"(?:there|to\s+get\s+there|instead)|on\s+foot)\b",
                lower,
            ):
                return "walk"
            if re.search(r"\bno\s+uber\b|\bwithout\s+uber\b", lower):
                return "public_transport"
            return "public_transport"
        return None

    @staticmethod
    def _extract_preferences(text: str, exclusions: list[str]) -> list[str]:
        lower = text.lower()
        preferences: list[str] = []

        if "not_too_fancy" not in exclusions:
            if re.search(r"\b(?:fancy|upscale|fine dining|high end)\b", lower):
                preferences.append("fancy")

        if re.search(r"\b(?:somewhere nice|nice place|something nice|nice)\b", lower):
            preferences.append("nice")

        if re.search(r"\b(?:casual|chill|relaxed|laid back|unhurried|easygoing)\b", lower):
            preferences.append("casual")

        if re.search(r"\b(?:fun|something fun|exciting|entertaining|adventurous)\b", lower):
            preferences.append("fun")

        if re.search(r"\b(?:romantic|intimate|cozy|cute)\b", lower):
            preferences.append("romantic")

        if re.search(r"\b(?:food[ -]focused|foodie|good food|great food|delicious|tasting|dinner|lunch|breakfast)\b", lower):
            preferences.append("food_focused")

        if re.search(r"\b(?:spend most (?:of it )?on dinner|most on dinner)\b", lower):
            preferences.append("prioritize_dinner")

        if re.search(r"\b(?:aesthetic|scenic|pretty|view)\b", lower):
            preferences.append("aesthetic")

        if "no_outdoors" not in exclusions:
            if re.search(r"\b(?:outdoors|nature|in the sun|open air)\b", lower):
                preferences.append("outdoors")

        if re.search(r"\b(?:cultural|culture|historic|history|museum|artsy)\b", lower):
            preferences.append("cultural")

        return preferences

    @staticmethod
    def _extract_activity_types(
        text: str, occasion: str | None, preferences: list[str]
    ) -> list[InformationCategory]:
        lower = text.lower()
        categories: list[InformationCategory] = []

        if re.search(r"\b(?:food|eat|dinner|lunch|breakfast|brunch|tasting|drinks|cocktail|restaurant|cafe|coffee)\b", lower) or "food_focused" in preferences:
            categories.append(InformationCategory.FOOD)

        if re.search(r"\b(?:walk|hike|park|garden|nature|beach|scenic)\b", lower) or "outdoors" in preferences:
            categories.append(InformationCategory.NATURE)

        if re.search(r"\b(?:culture|cultural|history|museum|art|heritage|guided)\b", lower) or "cultural" in preferences:
            categories.append(InformationCategory.CULTURE)

        if re.search(r"\b(?:movie|theatre|theater|show|music|live|comedy|entertainment)\b", lower):
            categories.append(InformationCategory.ENTERTAINMENT)

        if re.search(r"\b(?:spa|massage|wellness|relax)\b", lower):
            categories.append(InformationCategory.WELLNESS)

        if re.search(r"\b(?:market|shopping|mall|boutique)\b", lower):
            categories.append(InformationCategory.SHOPPING)

        if re.search(r"\b(?:fun|entertainment|activity|activities)\b", lower) or "fun" in preferences:
            for cat in (InformationCategory.FOOD, InformationCategory.NATURE, InformationCategory.CULTURE):
                if cat not in categories:
                    categories.append(cat)

        # If date, social outing, or celebration and no explicit activity stated, food is natural default
        if not categories and occasion in {"date", "friends", "casual_hangout", "birthday", "celebration", "family"}:
            categories.append(InformationCategory.FOOD)

        return categories

    @staticmethod
    def _extract_goal(text: str, occasion: str | None, rel: str | None) -> str:
        # Formulate a crisp, human-facing goal description
        if occasion == "date":
            partner = rel if rel in {"boyfriend", "girlfriend", "partner", "husband", "wife"} else "partner"
            return f"Plan a date with {partner}"
        if occasion == "birthday":
            if rel in {"mom", "mother", "dad", "father", "friend", "partner"}:
                return f"Plan a birthday celebration for {rel}"
            return "Plan a birthday celebration"
        if occasion == "celebration":
            return "Plan a celebration outing"
        if occasion == "friends":
            return "Plan an outing with friends"
        if occasion == "solo":
            return "Plan a solo outing"
        return text
