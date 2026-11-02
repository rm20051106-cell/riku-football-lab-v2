# RIKU FOOTBALL LAB — Development Roadmap

Updated: 2026-11-02
Target branch: `feature/riku-match-ai-analysis`

This roadmap records the user's feature-selection decisions. It is a planning document, not a claim that every listed feature is already implemented or runtime-verified.

## Development constraints

- Keep development and verification within the free tier and free tools.
- Work only on `feature/riku-match-ai-analysis` (or another explicitly approved development branch).
- Do not merge to the production/default branch.
- Do not deploy or publish to production.
- Do not introduce paid APIs, subscriptions, or services. If a paid dependency ever appears necessary, stop and obtain explicit approval before any change.
- Preserve existing features unless a separate, reviewed removal decision is made.
- Distinguish manually confirmed match observations from completed practice records. Never infer unobserved match facts.

## Approved features — priority order

1. **Dribbling breakthrough analysis** — record and assess 1v1 attempts, approach, change of direction, acceleration, route, outcome, and repeatable strengths/issues. Use confirmed observations; do not fabricate success rates from incomplete footage.
2. **Shooting and free-kick specialist analysis** — compare manually selected attempts and available pose/form measurements, including approach, plant foot, striking motion, body balance, and target/result when known.
3. **First-touch analysis** — assess receiving preparation, contact direction, first-touch destination, control, and next action from confirmed scenes.
4. **Transition analysis** — assess actions immediately after winning or losing possession, including reaction, first decision, support/pressing/recovery, and outcome where visible.
5. **Physical development tracking** — maintain dated measurements such as sprint, agility, jump, and other user-entered tests; compare like-for-like tests and show trends without inventing missing measurements.
6. **Riku-specific AI coach** — use available confirmed match reviews, practice logs, form records, and measurements to recommend age-appropriate next steps. Explain the evidence behind recommendations and hold when evidence is insufficient.
7. **Weekly and monthly growth reports** — summarize progress, recurring strengths, and priorities using actual saved records; clearly separate match evidence from practice completion.
8. **Example videos and practice explanations** — provide lightweight, free reference material and instructions for drills. Avoid paid media/API dependencies and respect media rights.
9. **Backup and data export** — provide a user-controlled way to export/backup records and explain limitations for large video files. Prefer free/local options.

## Deferred — do not implement now

- In-match correction ability analysis.
- Teammate coordination analysis.

Revisit only after the user explicitly changes this decision.

## Excluded from future scope

- Full-match chronological timeline analysis.
- Health/fatigue tracking.
- Coach-facing reports.

Do not add new UI, workflows, or automatic recommendations for these excluded features. Existing related code, if any, must not be deleted merely because of this roadmap; assess dependencies and obtain a separate decision before removal.

## Implementation order and acceptance principles

- Follow the priority order above, but first check existing code to avoid duplicating capabilities already present.
- Implement in small, independently testable increments while preserving current workflows.
- Use manually confirmed evidence for match analysis; missing or uncertain information must display as pending/unknown rather than be guessed.
- Keep match review records separate from practice completion records.
- Prefer local deterministic logic and existing free infrastructure; no paid AI inference/API is authorized.
- For each feature, run syntax/static checks and verify branch/commit. Do not claim iPhone runtime behavior unless it has actually been tested.
- No merge, production deployment, or publication is authorized by this roadmap.
