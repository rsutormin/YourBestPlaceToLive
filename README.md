# Your Best Place To Live

A world map for comparing countries by what matters to you. Sliders set how important each metric is. Each metric is scored by comparing countries, those scores are averaged with your weights, and the map paints the result from red through yellow to green.

## Run the map in dev mode

```bash
cd frontend
npm install
npm run dev
```

Vite prints a local URL, usually http://127.0.0.1:5173/.

```bash
npm test        # Vitest
npm run build   # typecheck and production build
```

## Publish

A push to `main` builds the frontend and deploys it with GitHub Actions. The site is https://rsutormin.github.io/YourBestPlaceToLive/. In the repository settings, set Pages → Build and deployment → Source to GitHub Actions before the first deploy.

## Refresh the data

World metrics are one JSON file each in `data/`. Europe metrics are in `data/europe/` (currently not in use). The map reads the combined World-scope file `frontend/src/world-metrics.json`.

```bash
cd processes
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
mix-metrics
```

`mix-metrics` keeps documents whose scope is World and writes them into the frontend file. These commands download a fresh copy first:

| Command | Source |
| --- | --- |
| `import-world-bank` | World Bank Open Data |
| `import-owid` | Our World in Data |
| `import-eurostat` | Eurostat |
| `import-oecd` | OECD |
| `import-bis` | Bank for International Settlements |
| `import-vdem` | Varieties of Democracy |
| `import-wikipedia` | English Wikipedia |
| `import-heritage` | Heritage Foundation Index of Economic Freedom |
| `import-open-meteo` | Open-Meteo |

Pass `--keys` to import a subset, for example `import-world-bank --keys gdp_per_capita_ppp`. After an import, run `mix-metrics` again so the map picks up the new files.

```bash
python -m pytest
```

Python 3.9 or newer. Attribution for the redistributed data is in [LICENSE](LICENSE).
