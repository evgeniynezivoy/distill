---
name: predicate-as-defense
title: Predicate As Defense
tags: [validation, architecture]
---

# Predicate As Defense

## Trigger

A business rule first allows a state, then validates on the way out. You ship the rule by adding a check after the write — and the next time the rule needs to evolve, you discover it was never enforced consistently.

## Bigger lesson

Validation is a **predicate at entry**, not a post-hoc check. If a rule says "you can't do X in state Y," that's a predicate the operation refuses to start under — not a sanity check at the end. Predicates compose; post-hoc checks drift apart over time and leave the system in inconsistent intermediate states.
