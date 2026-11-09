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

## Data

The API returns one row per run (`participate_data`: `openid`, `nickname`,
`day`, `boss_id`, `step`, `difficulty`, `level`, `total_damage`,
`is_final_hit`, `squad`, …). Runs are grouped per member in API order and
numbered per day, days start at 1. A member's total is the sum of their runs.

## Tests

```sh
python -m unittest discover -s tests -t .
```

## License

GNU Affero General Public License, version 3 or later (see [LICENSE](LICENSE)).
