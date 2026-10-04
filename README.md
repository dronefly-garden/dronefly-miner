# Dronefly Miner

This library supports fast local taxon name searches against
a database built from iNaturalist DWC-A exports.

It is used by [Dronefly bot](https://github.com/dronefly-garden/dronefly)
to support taxon name autocompletion. It would be impractical to
use iNaturalist API calls to do this, as it would be slow and/or
exceed the rate limit fairly quickly with anything more than
trivial workloads.

## Requirements

- Sufficient disk space for the files, about 300GB total:
    - `~/.local/share/pyinaturalist/*`
        - ~250GB iNaturalist DWC-A export files & derived work files
    - `~/.local/share/dronefly-miner/observations.db`
        - ~50GB database built from those files
- Time to complete the job, roughly 1.5 hrs on a system/network
  with the following specs:
    - *System:* Ryzen 7 255, 32GB ram, and nvme ssd
    - *Network:* 1Gbps residential FTH

## Build the database

1. Install uv from https://docs.astral.sh/uv
2. Build the database with:
```
uvx run dronefly-miner build
```

Confirm that the build is successful and restart the bot to
test autocompletion with `/taxon show taxon:`. Upon first
use, the results may be empty. Once the database connection
is primed, autocompletions should be fairly quick.

## Schedule the database build

When and how often you perform the database load is up to you.

- The iNaturalist taxonomy DWC-A archive is updated monthly.
- The iNaturalist observations DWC-A archive is updated weekly.
  It is used to improve relevance ranking of autocompletion
  results.
- Files will only be downloaded if newer versions are available.
- Daily, weekly, or monthly are all reasonable schedules:
    - *Daily* updates the DB as soon as possible after new files
      are published.
    - *Weekly* balances timeliness of receiving updates with the
      cost of performing them.
    - *Monthly* stil provides good-enough update frequency while
      reducing processing cost.

After the initial build, schedule regular builds. For example,
assuming the bot runs as user `redbot`, to run monthly at
midnight on the first day of each month, login as `redbot`
and create the scheduled job with `crontab -e`

```
# m h dom mon dow   command
0 0 1 * * /home/redbot/.local/bin/uvx dronefly-miner build
```
