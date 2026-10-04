# Dronefly Miner

This library supports fast local taxon name searches against
a database built from iNaturalist DWC-A exports.

It is used by [Dronefly bot](https://github.com/dronefly-garden/dronefly)
to support taxon name autocompletion. It would be impractical to
use iNaturalist API calls to do this, as it would be slow and/or
exceed the rate limit fairly quickly with anything more than
trivial workloads.
