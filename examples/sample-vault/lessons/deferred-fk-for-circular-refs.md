---
name: deferred-fk-for-circular-refs
title: Deferred FK for Circular Refs
tags: [db, migrations]
---

# Deferred FK for Circular Refs

## Bigger lesson

When two tables reference each other, a standard FK blocks the first INSERT — neither side can be inserted before the other exists. The fix isn't to drop the FK or restructure the data model; it's to declare the constraint `DEFERRABLE INITIALLY DEFERRED`. The check then runs at commit, after both rows are visible. This is also the right tool for batch loaders that rebuild interlinked data.
