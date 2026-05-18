---
name: deferred-fk-for-circular-refs
title: Deferred FK for Circular Refs
tags: [db, migrations]
---

# Deferred FK for Circular Refs

## Bigger lesson
Когда две таблицы ссылаются друг на друга, обычный FK блокирует одинарный INSERT. Решение — DEFERRABLE INITIALLY DEFERRED.
