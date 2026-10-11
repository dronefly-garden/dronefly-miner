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

- Sufficient disk space for the files, about 30GB total:
    - `~/.local/share/dronefly-miner/*`
        - ~28 GB iNaturalist DWC-A observations
        - ~660 MB iNaturalist DWC-A taxonomy
        - ~770 MB database built from those files
- A build takes under a half hour on the developer's system:
    - *System:* Ryzen 7 255, 32GB ram, and nvme ssd
    - *Network:* 1Gbps residential FTH

## Build the database

1. Install uv from https://docs.astral.sh/uv
2. Perform an initial build of the database with:
```
uvx dronefly-miner build
```

Confirm that the build is successful and restart the bot to
test autocompletion with `/taxon show`. Upon first use, the
results may be empty. Once the database connection is
primed, autocompletions should be fairly quick.

## Schedule database updates

In order to update the database as soon as iNaturalist
publishes new DWC-A archives of either the taxonomy or
GBIF observations data sets, schedule nightly runs
of `dronefly-miner build`. Archives won't be downloaded
unless newer versions are available, and the database
build will be skipped if nothing was downloaded and the
database exists.

## Example scheduled build

Dronefly bot runs from the `redbot` account. Dronefly-miner
builds run on the same account daily at 1 am local time at
reduced priority to minimize impact on other processes:

```sh
$ cat > ~/bin/dronefly-miner.sh
#!/bin/bash
cd /home/redbot/dronefly-miner
/home/synrg/.local/bin/uv run dronefly-miner build > /home/redbot/.local/share/dronefly-miner/build.log 2>&1
$ chmod a+rx ~/bin/dronefly-miner.sh
$ crontab -e
… *edit to match below*
$ crontab -l
# m h dom mon dow   command
  0 1   *   *   *   /bin/nice -n 19 /home/redbot/bin/dronefly-miner.sh
```
