# Proposals

## In CSV, include diff stats

Show the number of removals, additions, and changes as reported by PageFreezer.

## Create a view that shows only diffs

PageFreezer includes in its result an HTML that *highlights* differences. This
view could hide all non-differences, showing only the changes regions.
(Versionista does this already.)

## Signals to feed into prioritization heuristic

### Automated


Per row:
* type of change
* contains date
* contains non-visible tag
* contains any tag
* contains number
* contains link tag
* total characters changed
* (maybe!) NLP metrics like "edit distance"

Per document:
* total characters changed
* history (timing) of changes

### Manual

* visual region of page highlighted as important or unimportant
* written description to be parsed by a programmer

## Scale up to a "citizen science" effort (like Galaxy Zoo) for categorizing
