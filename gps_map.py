#!/usr/bin/env python3
"""
GPS Map Viewer
Lit un fichier NMEA (GPS*.txt) et affiche le tracé sur OpenStreetMap.

Usage :
    python3 gps_map.py [fichier.txt]
    Si aucun fichier n'est passé, cherche GPS*.txt dans le répertoire courant.
"""

import sys
import os
import math
import json
import webbrowser
import glob
import folium


# ── Conversion NMEA → degrés décimaux ───────────────────────────────

def nmea_to_decimal(coord: str, direction: str) -> float:
    """Convertit DDMM.MMMM / DDDMM.MMMM en degrés décimaux."""
    dot = coord.index('.')
    degrees = int(coord[:dot - 2])
    minutes = float(coord[dot - 2:])
    value = degrees + minutes / 60.0
    return -value if direction in ('S', 'W') else value


# ── Calcul de distance (formule Haversine) ───────────────────────────

def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance en mètres entre deux coordonnées GPS."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi   = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


# ── Conversion heure NMEA → secondes ────────────────────────────────

def parse_time_s(time_str: str) -> float | None:
    """Convertit 'HH:MM:SS.SSS UTC' en secondes depuis minuit."""
    try:
        t = time_str.replace(' UTC', '')
        h, m, s = t.split(':')
        return int(h) * 3600 + int(m) * 60 + float(s)
    except Exception:
        return None


def _smooth(data: list, window: int = 3) -> list:
    """Moyenne mobile symétrique, ignore les None."""
    hw = window // 2
    result = []
    for i in range(len(data)):
        vals = [data[j] for j in range(max(0, i - hw), min(len(data), i + hw + 1))
                if data[j] is not None]
        result.append(round(sum(vals) / len(vals), 2) if vals else None)
    return result


# ── Parsing d'une trame $GPGGA ────────────────────────────────────────

def parse_gpgga(line: str) -> dict | None:
    """
    Retourne un dict {time, lat, lon, alt, sats, hdop} si la trame est valide
    (fix_quality > 0 et coordonnées présentes), sinon None.
    """
    parts = line.strip().split(',')
    if len(parts) < 10:
        return None
    try:
        time_raw = parts[1]
        lat_str  = parts[2]
        lat_dir  = parts[3]
        lon_str  = parts[4]
        lon_dir  = parts[5]
        fix      = int(parts[6]) if parts[6] else 0
        sats     = int(parts[7]) if parts[7] else 0
        hdop     = float(parts[8]) if parts[8] else None
        alt      = float(parts[9]) if parts[9] else None
    except (ValueError, IndexError):
        return None

    if fix == 0 or not lat_str or not lon_str:
        return None

    try:
        lat = nmea_to_decimal(lat_str, lat_dir)
        lon = nmea_to_decimal(lon_str, lon_dir)
    except (ValueError, IndexError):
        return None

    # Formatage de l'heure UTC
    if len(time_raw) >= 6:
        time_fmt = f"{time_raw[0:2]}:{time_raw[2:4]}:{time_raw[4:]} UTC"
    else:
        time_fmt = time_raw

    return {
        'time': time_fmt,
        'lat':  lat,
        'lon':  lon,
        'alt':  alt,
        'sats': sats,
        'hdop': hdop,
    }


# ── Lecture du fichier NMEA ──────────────────────────────────────────

def load_points(filepath: str) -> list[dict]:
    points = []
    with open(filepath, 'r', errors='replace') as f:
        for line in f:
            if line.startswith('$GPGGA'):
                pt = parse_gpgga(line)
                if pt:
                    points.append(pt)
    return points


# ── Création de la carte folium ──────────────────────────────────────

def build_map(points: list[dict], source_file: str) -> folium.Map:
    coords = [(p['lat'], p['lon']) for p in points]

    # Centre de la carte
    center_lat = sum(p['lat'] for p in points) / len(points)
    center_lon = sum(p['lon'] for p in points) / len(points)

    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=17,
        tiles='OpenStreetMap',
    )

    # ── Tracé du parcours ──
    folium.PolyLine(
        coords,
        color='#1a6fbf',
        weight=4,
        opacity=0.85,
        tooltip='Parcours GPS',
    ).add_to(m)

    # ── Marqueur de départ (vert) ──
    p0 = points[0]
    folium.Marker(
        location=coords[0],
        popup=folium.Popup(
            f"<b>🟢 Départ</b><br>"
            f"Heure&nbsp;: {p0['time']}<br>"
            f"Alt&nbsp;&nbsp;&nbsp;: {p0['alt']:.1f} m<br>"
            f"Sats&nbsp;&nbsp;: {p0['sats']}",
            max_width=180,
        ),
        icon=folium.Icon(color='green', icon='play', prefix='fa'),
    ).add_to(m)

    # ── Marqueur d'arrivée (rouge) ──
    pN = points[-1]
    folium.Marker(
        location=coords[-1],
        popup=folium.Popup(
            f"<b>🔴 Arrivée</b><br>"
            f"Heure&nbsp;: {pN['time']}<br>"
            f"Alt&nbsp;&nbsp;&nbsp;: {pN['alt']:.1f} m<br>"
            f"Sats&nbsp;&nbsp;: {pN['sats']}",
            max_width=180,
        ),
        icon=folium.Icon(color='red', icon='stop', prefix='fa'),
    ).add_to(m)

    # ── Points intermédiaires cliquables (max 30) ──
    n = len(points)
    step = max(1, n // 30)
    for i in range(step, n - 1, step):
        p = points[i]
        hdop_str = f"{p['hdop']:.2f}" if p['hdop'] is not None else "—"
        alt_str  = f"{p['alt']:.1f} m" if p['alt'] is not None else "—"
        popup_html = (
            f"<b>Point {i}/{n}</b><br>"
            f"Heure&nbsp;&nbsp;&nbsp;: {p['time']}<br>"
            f"Lat&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;: {p['lat']:.6f}°<br>"
            f"Lon&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;: {p['lon']:.6f}°<br>"
            f"Altitude : {alt_str}<br>"
            f"Satellites : {p['sats']}<br>"
            f"HDOP&nbsp;&nbsp;&nbsp;&nbsp;: {hdop_str}"
        )
        folium.CircleMarker(
            location=(p['lat'], p['lon']),
            radius=5,
            color='#1a6fbf',
            fill=True,
            fill_color='#ffffff',
            fill_opacity=1.0,
            weight=2,
            popup=folium.Popup(popup_html, max_width=200),
        ).add_to(m)

    return m


# ── Statistiques ─────────────────────────────────────────────────────

def compute_stats(points: list[dict]) -> dict:
    total_dist = sum(
        haversine_m(points[i-1]['lat'], points[i-1]['lon'],
                    points[i]['lat'],   points[i]['lon'])
        for i in range(1, len(points))
    )
    alts = [p['alt'] for p in points if p['alt'] is not None]
    return {
        'count':    len(points),
        'dist_m':   total_dist,
        'alt_min':  min(alts) if alts else None,
        'alt_max':  max(alts) if alts else None,
    }


# ── Graphiques altitude + vitesse ────────────────────────────────────

def add_charts(m: folium.Map, points: list[dict]) -> None:
    """
    Injecte deux graphiques côte à côte sous la carte :
      - gauche : profil altimétrique (m) en fonction de la distance
      - droite  : vitesse (km/h) lissée en fonction de la distance
    Le marqueur rouge sur la carte suit le curseur sur l'un ou l'autre graphique.
    """
    # Échantillonnage (max 600 points)
    n = len(points)
    step = max(1, n // 600)
    sampled = points[::step]

    # Distance cumulée
    distances: list[float] = [0.0]
    for i in range(1, len(sampled)):
        distances.append(distances[-1] + haversine_m(
            sampled[i-1]['lat'], sampled[i-1]['lon'],
            sampled[i]['lat'],   sampled[i]['lon']))

    alts  = [p['alt']  for p in sampled]
    times = [p['time'] for p in sampled]
    lats  = [p['lat']  for p in sampled]
    lons  = [p['lon']  for p in sampled]
    labels = [f"{d:.0f}" for d in distances]

    # Vitesse instantanée (km/h) entre points consécutifs, puis lissage 5 pts
    speeds_raw: list[float | None] = [None]
    for i in range(1, len(sampled)):
        t1 = parse_time_s(sampled[i-1]['time'])
        t2 = parse_time_s(sampled[i]['time'])
        dd = distances[i] - distances[i-1]
        if t1 is not None and t2 is not None:
            dt = t2 - t1
            if dt < 0:
                dt += 86400         # passage minuit
            speeds_raw.append(dd / dt * 3.6 if dt > 0 else None)
        else:
            speeds_raw.append(None)
    speeds = _smooth(speeds_raw, window=5)

    map_name = m.get_name()
    CHART_H  = 230

    css = f"""
    <style>
      html, body {{ margin: 0; padding: 0; overflow: hidden; }}
      #{map_name} {{ position: relative !important; width: 100% !important; }}
      #charts-panel {{
          display: flex;
          width: 100%;
          height: {CHART_H}px;
          background: #f5f7fa;
          border-top: 2px solid #d0d7de;
          font-family: Arial, sans-serif;
          box-sizing: border-box;
      }}
      .chart-pane {{
          flex: 1;
          padding: 6px 14px 10px 14px;
          box-sizing: border-box;
          min-width: 0;
      }}
      .chart-pane + .chart-pane {{ border-left: 1px solid #d0d7de; }}
      .chart-pane h4 {{
          margin: 0 0 3px 0;
          font-size: 11px;
          color: #666;
          letter-spacing: 0.8px;
          text-transform: uppercase;
      }}
    </style>
    """

    script = f"""
    <div id="charts-panel">
      <div class="chart-pane">
        <h4>Profil altimétrique</h4>
        <canvas id="altCanvas"></canvas>
      </div>
      <div class="chart-pane">
        <h4>Vitesse (km/h)</h4>
        <canvas id="speedCanvas"></canvas>
      </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <script>
    (function() {{
      const CHART_H    = {CHART_H};
      const MAP_NAME   = '{map_name}';
      const lats       = {json.dumps(lats)};
      const lons       = {json.dumps(lons)};
      const alts       = {json.dumps(alts)};
      const speeds     = {json.dumps(speeds)};
      const times      = {json.dumps(times)};
      const distLabels = {json.dumps(labels)};

      // ── Redimensionnement de la carte ────────────────────────────────
      function resizeMap() {{
        const mapDiv = document.getElementById(MAP_NAME);
        if (!mapDiv) return;
        mapDiv.style.height = (window.innerHeight - CHART_H) + 'px';
        const lmap = window[MAP_NAME];
        if (lmap && lmap.invalidateSize) lmap.invalidateSize();
      }}
      document.addEventListener('DOMContentLoaded', () => {{
        resizeMap();
        window.addEventListener('resize', resizeMap);
        setTimeout(resizeMap, 400);
      }});

      // ── Marqueur mobile partagé entre les deux graphiques ────────────
      let hoverMarker = null;
      function moveHoverMarker(i) {{
        if (lats[i] == null) return;
        const lmap = window[MAP_NAME];
        if (!lmap) return;
        if (!hoverMarker) {{
          hoverMarker = L.circleMarker([lats[i], lons[i]], {{
            radius: 7, color: '#c0392b', fillColor: '#e74c3c',
            fillOpacity: 0.9, weight: 2,
          }}).addTo(lmap);
        }} else {{
          hoverMarker.setLatLng([lats[i], lons[i]]);
        }}
      }}
      function removeHoverMarker() {{
        if (hoverMarker) {{ hoverMarker.remove(); hoverMarker = null; }}
      }}

      // ── Fabrique un objet options Chart.js commun ────────────────────
      function makeOptions(yLabel, yMin, yMax, tooltipLabel) {{
        return {{
          responsive: true,
          maintainAspectRatio: false,
          animation: false,
          interaction: {{ mode: 'index', intersect: false }},
          onHover: (_e, elements) => {{
            if (elements.length > 0) moveHoverMarker(elements[0].index);
          }},
          plugins: {{
            legend: {{ display: false }},
            tooltip: {{
              backgroundColor: 'rgba(20,20,20,0.85)',
              padding: 10,
              cornerRadius: 6,
              callbacks: {{
                title: (items) => 'Distance : ' + distLabels[items[0].dataIndex] + ' m',
                label: (item)  => [
                  tooltipLabel + (item.parsed.y != null
                    ? item.parsed.y.toFixed(1) : '—'),
                  'Heure    : ' + times[item.dataIndex],
                ],
              }}
            }}
          }},
          scales: {{
            x: {{
              ticks: {{ maxTicksLimit: 9, maxRotation: 0, font: {{ size: 11 }} }},
              title: {{ display: true, text: 'Distance (m)',
                        font: {{ size: 11 }}, color: '#777' }}
            }},
            y: {{
              min: yMin, max: yMax,
              ticks: {{ font: {{ size: 11 }} }},
              title: {{ display: true, text: yLabel,
                        font: {{ size: 11 }}, color: '#777' }}
            }}
          }}
        }};
      }}

      document.addEventListener('DOMContentLoaded', () => {{

        // ── Graphique altitude ─────────────────────────────────────────
        const validAlts = alts.filter(v => v != null);
        const altMin = Math.min(...validAlts);
        const altMax = Math.max(...validAlts);
        const altPad = Math.max(5, (altMax - altMin) * 0.15);

        new Chart(
          document.getElementById('altCanvas').getContext('2d'),
          {{
            type: 'line',
            data: {{
              labels: distLabels,
              datasets: [{{
                data: alts,
                borderColor: '#1a6fbf',
                backgroundColor: 'rgba(26,111,191,0.13)',
                fill: true, pointRadius: 0, borderWidth: 2,
                tension: 0.35, spanGaps: true,
              }}]
            }},
            options: makeOptions(
              'Altitude (m)', altMin - altPad, altMax + altPad,
              'Altitude : ',
            ),
          }}
        );
        document.getElementById('altCanvas')
          .addEventListener('mouseleave', removeHoverMarker);

        // ── Graphique vitesse ──────────────────────────────────────────
        const validSpd = speeds.filter(v => v != null);
        const spdMax   = Math.ceil(Math.max(...validSpd) * 1.2) || 10;

        new Chart(
          document.getElementById('speedCanvas').getContext('2d'),
          {{
            type: 'line',
            data: {{
              labels: distLabels,
              datasets: [{{
                data: speeds,
                borderColor: '#27ae60',
                backgroundColor: 'rgba(39,174,96,0.13)',
                fill: true, pointRadius: 0, borderWidth: 2,
                tension: 0.35, spanGaps: true,
              }}]
            }},
            options: makeOptions(
              'Vitesse (km/h)', 0, spdMax,
              'Vitesse  : ',
            ),
          }}
        );
        document.getElementById('speedCanvas')
          .addEventListener('mouseleave', removeHoverMarker);

      }});
    }})();
    </script>
    """

    m.get_root().header.add_child(folium.Element(css))
    m.get_root().html.add_child(folium.Element(script))


# ── Bandeau d'informations sur la carte ─────────────────────────────

def add_info_panel(m: folium.Map, stats: dict, filename: str) -> None:
    alt_line = ""
    if stats['alt_min'] is not None:
        alt_line = f"Altitude : {stats['alt_min']:.0f} – {stats['alt_max']:.0f} m"

    html = f"""
    <div style="
        position: fixed;
        top: 12px; left: 50px;
        z-index: 9999;
        background: rgba(255,255,255,0.93);
        padding: 10px 14px;
        border-radius: 8px;
        border: 1px solid #aaa;
        font-family: Arial, sans-serif;
        font-size: 13px;
        line-height: 1.6;
        box-shadow: 2px 2px 6px rgba(0,0,0,0.2);
    ">
        <b>GPS Logger — {os.path.basename(filename)}</b><br>
        {stats['count']} points enregistrés<br>
        Distance totale : {stats['dist_m']:.0f} m ({stats['dist_m']/1000:.2f} km)<br>
        {alt_line}
    </div>
    """
    m.get_root().html.add_child(folium.Element(html))


# ── Point d'entrée ───────────────────────────────────────────────────

def main() -> None:
    # Choix du fichier source
    if len(sys.argv) > 1:
        gps_file = sys.argv[1]
    else:
        candidates = sorted(glob.glob('GPS*.txt') + glob.glob('gps*.txt'))
        if not candidates:
            print("Aucun fichier GPS*.txt trouvé. Usage : python3 gps_map.py <fichier.txt>")
            sys.exit(1)
        gps_file = candidates[-1]   # le plus récent (tri alphabétique)
        print(f"Fichier détecté automatiquement : {gps_file}")

    if not os.path.exists(gps_file):
        print(f"Fichier introuvable : {gps_file}")
        sys.exit(1)

    # Parsing
    print(f"Lecture de {gps_file} …")
    points = load_points(gps_file)

    if not points:
        print("Aucune position GPS valide dans ce fichier (fix_quality == 0).")
        sys.exit(1)

    # Statistiques
    stats = compute_stats(points)
    print(f"  {stats['count']} positions valides")
    print(f"  Distance totale  : {stats['dist_m']:.1f} m ({stats['dist_m']/1000:.3f} km)")
    if stats['alt_min'] is not None:
        print(f"  Altitude min/max : {stats['alt_min']:.1f} m / {stats['alt_max']:.1f} m")

    # Carte
    print("Génération de la carte …")
    m = build_map(points, gps_file)
    add_info_panel(m, stats, gps_file)
    add_charts(m, points)

    # Sauvegarde
    out_file = os.path.splitext(os.path.abspath(gps_file))[0] + '_map.html'
    m.save(out_file)
    print(f"Carte sauvegardée : {out_file}")

    # Ouverture dans le navigateur
    webbrowser.open('file://' + out_file)


if __name__ == '__main__':
    main()
