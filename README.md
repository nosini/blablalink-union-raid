# blablalink-union-raid

Per-member Union Raid damage from [blablalink.com](https://www.blablalink.com/):
each member's damage in every run (up to three per day), the daily total and
the season total.

No dependencies beyond Python 3.11.

## Status: not tested against real data

Union Raid data is only served to logged-in members of the union, and this
was written without access to one. The request and data formats come from
the website's own JavaScript (the Shifty's Pad union raid page), and the
tests use synthetic data shaped like that. **The first run with a real union
may need adjustments.** If it fails or the numbers look wrong, run
`fetch`, remove names and ids from the file and share it.

## Usage

Run `python -m blablalink_union_raid` from this folder, or
`pip install .` for the `blablalink-union-raid` command.

### Without giving the tool your login

1. Open the Union Raid page in Shifty's Pad while logged in.
2. In the browser's developer tools, Network tab, find the request
   `GetUnionRaidData` (current season) or `GetUnionRaidDataOfGuildSeason`
   (a past season). Save its **response** as `raid.json` ("Copy response").
3. Report on it:

```sh
python -m blablalink_union_raid report raid.json
python -m blablalink_union_raid report raid.json --day 2
python -m blablalink_union_raid report raid.json --format summary-csv > raid.csv
python -m blablalink_union_raid report raid.json --member alice --format json
```

Formats: `table` (default, one table per day plus season totals),
`summary-csv` (a row per member and day, runs side by side, with day and
member totals), `runs-csv` (a row per run), `json`.

### Fetching directly

Export your blablalink.com cookies from the browser as a Netscape
`cookies.txt`. They are your login: keep the file private (this repo's
`.gitignore` excludes `cookies*.txt`). They are only sent to
`api.blablalink.com`.

The ids appear in the payload of the requests above (Network tab):

```sh
# current season
python -m blablalink_union_raid fetch --cookies cookies.txt \
  --guild-id GUILD --area-id AREA --openid 29080-123… -o raid.json
# a past season
python -m blablalink_union_raid fetch --cookies cookies.txt \
  --guild-id GUILD --area-id AREA --season-id SEASON -o raid.json
python -m blablalink_union_raid report raid.json
```

`raid.json` holds every member's names and openids; treat it as private too.

## History and season comparison

Keep each season's result, then see who moved up or down in the damage
ranking:

```sh
# after saving each season's response as raid.json (see above)
python -m blablalink_union_raid ingest raid.json --season 2026-10
python -m blablalink_union_raid seasons
python -m blablalink_union_raid compare                  # last two added
python -m blablalink_union_raid compare --from 2026-09 --to 2026-10
python -m blablalink_union_raid compare --format csv     # or json
```

```
2026-09 -> 2026-10
Member  Rank  Was  Move            Total            Was          Change
Bob        1    3  up 2    5,500,000,000  2,600,000,000  +2,900,000,000
Dave       2    -  new     2,500,000,000              -
Alice      3    1  down 2  1,000,000,000  3,900,000,000  -2,900,000,000
Carol      -    2  absent              -  3,000,000,000
```

- `report` reads a stored season too, without the JSON file:
  `report --season 2026-10`, or just `report` for the latest one. All its
  options (`--day`, `--member`, `--format`) work the same.
- A stored season's report also compares with the season before it: the
  season totals show each member's rank, their rank before, how far they
  moved and the damage change, and members with no runs are listed below.
  `summary-csv` and `json` get the same data. Use `--against SEASON` to pick
  another season (also for a report from a file, which otherwise has no
  comparison) or `--no-compare` to turn it off. A single `--day` has no
  comparison, since it belongs to the season totals. `--member` only filters
  what is shown; ranks are always those of the whole union.
- Rank is by total damage in the season, highest first. Members are matched
  by openid, so a renamed member keeps their history and shows the new name.
- `new`: wasn't in the older season. `absent`: has no runs in the newer one.
  The data only lists members who fought, so absent can also mean a member who
  skipped the raid, not only one who left the union.
- Seasons are ordered by name, with numbers compared as numbers (`2026-09`
  before `2026-10`, `S9` before `S10`), whatever order you ingest them in. The
  default comparison is the last two; the heading of the output shows which.
  Use names that sort chronologically, or pick the pair with `--from` and
  `--to`. Ingesting a name again replaces it, so a running season can be
  updated as it goes.
- The history is a SQLite file at
  `~/.local/share/blablalink-union-raid/history.sqlite3` (or under
  `$XDG_DATA_HOME`; override with `--db`), readable only by you. It holds
  member names and openids and is deliberately outside this repository.
  Delete the file to forget everything.

## Data

The API returns one row per run (`participate_data`: `openid`, `nickname`,
`day`, `boss_id`, `step`, `difficulty`, `level`, `total_damage`,
`is_final_hit`, `element_id`, `icon_id`, `monster_model_id`, `name_localvalues`
and `squad`). The history keeps all of them, with the boss name in the
language chosen at ingest, including the squad: the characters used in the run with
their `tid`, `costume_id`, `lv` (character level) and `combat` (combat power).
`level` is the raid tier of the run; the rows have no player (commander)
level. `runs-csv` and `json` include the squad, element and boss model.

Databases made by an earlier version are updated when opened. Runs ingested
before that have no squad data until you ingest their file again. Runs are grouped per member in API order and
numbered per day, days start at 1. A member's total is the sum of their runs.

## Tests

```sh
python -m unittest discover -s tests -t .
```

## License

GNU Affero General Public License, version 3 or later (see [LICENSE](LICENSE)).
