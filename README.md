# Dronefly Miner

This library supports fast local taxon name searches against
a database built from iNaturalist DWC-A exports using
[pyinaturalist-convert](https://github.com/pyinat/pyinaturalist-convert).

It is used by [Dronefly bot](https://github.com/dronefly-garden/dronefly)
to support taxon name autocompletion.

By using a local database instead of the iNaturalist API, Dronefly bot
is able to keep up with moderate to heavy demand without exceeding iNat
API rate limits.

## Requirements

- Sufficient disk space for the files, about 300GB total if you
  perform full builds (highly recommended):
    - `~/.local/share/pyinaturalist/*`
        - ~250GB iNaturalist DWC-A export files & derived work files
    - `~/.local/share/dronefly-miner/observations.db`
        - ~50GB database built from those files
- A full build takes a few hours on the developer's system, whereas
  a regular build takes minutes.
    - *System:* Ryzen 7 255, 32GB ram, and nvme ssd
    - *Network:* 1Gbps residential FTH

## Build the database

1. Install uv from https://docs.astral.sh/uv
2. Perform an initial full run of the database with:
```
uvx run dronefly-miner build --full
```

Confirm that the build is successful and restart the bot to
test autocompletion with `/taxon show taxon:`. Upon first
use, the results may be empty. Once the database connection
is primed, autocompletions should be fairly quick.

## Schedule the database updates

Frequency of database updates is up to you. Consider
the following:

- Files for either data set will only be downloaded if newer
  versions are available.
- The iNaturalist taxonomy DWC-A archive is updated monthly.
  - This fairly small data set that loads quickly and should
    not interrupt bot functions while loading.
- The iNaturalist observations DWC-A archive is updated weekly.
  - This is a massive data set that takes a long time to load
    and disrupts autocompletions while loading.

### Recommended schedule

In order to update the taxonomy as soon as iNaturalist
publishes a new data set, but without minimal disruption to users,
we recommend nightly builds without `--full`:

```
uvx dronefly-miner build
```

The more costly full build should be performed at most weekly,
and monthly is probably sufficient:

```
uvx dronefly-miner build --full
```

Full builds can be skipped entirely, but relevance ranking
will suffer. A compromise that might work for you is to
schedule less frequent full builds, or leave it as a manual
step on an as-needed basis. Any new taxa added to the
taxonomy will be downranked in the results without updates
to the aggregated observation counts, but for the most part,
relevance won't suffer much from working off of outdated
observation counts.

Database updates place a lot of demand on CPU. To give other
processes on the system during database updates, reduce
priority, e.g.
```
nice -n 19 uvx dronefly-miner build --full
```

### Example scheduled job configuration

Dronefly runs on the `redbot` account. The taxonomy is updated at midnight
nightly, and the observation counts are updated at half past midnight monthly:

```sh
$ crontab -l
# m h dom mon dow   command
  0 0   *   *   1   /bin/nice -n 19 /home/redbot/.local/bin/uvx dronefly-miner build
 30 0   1   *   *   /bin/nice -n 19 /home/redbot/.local/bin/uvx dronefly-miner build --full
```
