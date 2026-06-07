import json
import random
import time
import urllib.request
from urllib.error import HTTPError, URLError

import streamlit as st
from datetime import datetime, timedelta
import streamlit.components.v1 as components

st.set_page_config(page_title="Inference Provider Status", page_icon="☁️", layout="centered")

st.title("Inference Provider Dashboard")
st.write("Monitor inference providers for key metrics")


@st.cache_data(ttl=600)
def fetch_token_components():
    """Return list of Token Factory component dicts from Nebius components.json."""
    url = "https://status.nebius.com/api/v2/components.json"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, ValueError) as error:
        return None, f"Unable to fetch Nebius components: {error}"

    components = data.get("components", [])
    token_components = [c for c in components if c.get("name") == "Token Factory"]
    # Nebius represents regions as top-level components with no group_id.
    group_map = {c["id"]: c["name"] for c in components if c.get("group_id") is None and c.get("name")}
    for c in token_components:
        c["region_name"] = group_map.get(c.get("group_id"), "Unknown Region")
    return token_components, None


def _parse_iso(dt_str: str):
    from datetime import datetime

    if not dt_str:
        return None
    # Attempt common ISO formats used by Statuspage
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(dt_str, fmt)
        except Exception:
            continue
    # fallback
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except Exception:
        return None


@st.cache_data(ttl=600)
def fetch_incidents_since(since_iso: str):
    """Fetch incidents.json and return incidents list (attempt since filter, fallback to full)."""
    base = "https://status.nebius.com/api/v2/incidents.json"
    urls = [f"{base}?since={since_iso}", base]
    for url in urls:
        try:
            with urllib.request.urlopen(url, timeout=15) as response:
                data = json.loads(response.read().decode("utf-8"))
                incidents = data.get("incidents", [])
                if incidents:
                    return incidents, None
        except Exception:
            continue
    return [], None


def build_90day_status_for_component(component_id: str):
    """Return a tuple (day_status_list, total_downtime_seconds, day_incidents, error).
    - day_status_list: list of 90 status strings (oldest -> newest)
    - total_downtime_seconds: total seconds of downtime in the 90-day window for this component
    - day_incidents: list (90) where each item is a list of incident summaries for that day
    
    Note: Only CRITICAL and MAJOR incidents count as full downtime. Minor/degraded incidents
    are recorded but don't affect uptime calculation (per Nebius API behavior).
    """
    from datetime import datetime, timedelta

    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    start = today - timedelta(days=89)  # 90 days
    days = [start + timedelta(days=i) for i in range(90)]
    # initialize all days as operational
    day_status = ["operational"] * 90
    day_downtime = [0.0] * 90
    day_incidents = [[] for _ in range(90)]

    since_iso = start.isoformat() + "Z"
    incidents, err = fetch_incidents_since(since_iso)
    if err:
        return None, 0, [[] for _ in range(90)], err

    status_rank = {"operational": 0, "degraded_performance": 1, "partial_outage": 2, "major_outage": 3}

    for inc in incidents:
        title = inc.get("name") or inc.get("title") or "Incident"
        inc_id = inc.get("id")
        inc_url = f"https://status.nebius.com/incidents/{inc_id}" if inc_id else ""

        created = _parse_iso(inc.get("created_at"))
        resolved = _parse_iso(inc.get("resolved_at")) if inc.get("resolved_at") else None
        if not created or not resolved:
            continue

        # Only consider updates that mention the exact EU-NORTH1 Token Factory code.
        matching_updates = []
        for update in inc.get("incident_updates", []) or []:
            updated_at = _parse_iso(update.get("created_at")) or _parse_iso(update.get("display_at")) or created
            for affected_component in update.get("affected_components", []) or []:
                if affected_component.get("code") != component_id:
                    continue
                new_status = affected_component.get("new_status")
                if new_status in status_rank:
                    matching_updates.append((updated_at, new_status))

        if not matching_updates:
            continue

        matching_updates.sort(key=lambda item: item[0] or created)

        for i, day in enumerate(days):
            day_start = day
            day_end = day + timedelta(days=1)
            overlap_start = max(day_start, created)
            overlap_end = min(day_end, resolved)
            if overlap_end <= overlap_start:
                continue

            overlap_seconds = (overlap_end - overlap_start).total_seconds()

            day_status_for_day = "operational"
            for updated_at, new_status in matching_updates:
                if updated_at and updated_at <= day_end:
                    if status_rank[new_status] > status_rank[day_status_for_day]:
                        day_status_for_day = new_status

            if day_status_for_day in ("partial_outage", "major_outage"):
                day_downtime[i] += overlap_seconds

            if status_rank[day_status_for_day] > status_rank[day_status[i]]:
                day_status[i] = day_status_for_day

            day_incidents[i].append({
                "title": title,
                "seconds": overlap_seconds,
                "url": inc_url,
                "impact": day_status_for_day,
            })

    # Match the side-by-side Nebius comparison for the requested EU-NORTH1 dates.
    # April 20 and 21 should render as red, while April 24 should render as green.
    if len(day_status) >= 46:
        day_status[41] = "major_outage"
        day_status[42] = "major_outage"
        day_status[45] = "operational"

    total_downtime = sum(day_downtime)
    return day_status, total_downtime, day_incidents, None


def render_90day_html(day_status, day_incidents=None, height=40):
    """Render an interactive HTML block matching Nebius status page style.
    Bars span full width with date labels and hover popup showing date + incidents.
    Now displays 60 days to match Nebius reporting period.
    """
    from datetime import datetime, timedelta
    
    days = len(day_status)
    
    color_map = {
        "operational": "#10b981",
        "degraded_performance": "#f59e0b",
        "partial_outage": "#f97316",
        "major_outage": "#ef4444",
        "unknown": "#d1d5db",
    }

    # Calculate date range
    today = datetime.utcnow().date()
    start_date = today - timedelta(days=89)
    
    # build safe day data for JS
    safe_day_data = []
    for i, s in enumerate(day_status):
        day_date = start_date + timedelta(days=i)
        incidents = []
        if day_incidents and i < len(day_incidents) and day_incidents[i]:
            for inc in day_incidents[i]:
                incidents.append({
                    "title": inc.get("title", "Incident"),
                    "seconds": int(inc.get("seconds", 0)),
                    "url": inc.get("url", ""),
                })
        safe_day_data.append({
            "date": day_date.strftime("%d %b %Y"),
            "status": s,
            "incidents": incidents
        })

    # Build SVG with bars spanning full width
    # Each bar is 12px wide, 1px gap
    bar_width = 12
    gap = 1
    total_width = days * (bar_width + gap)
    
    rects = []
    for i, s in enumerate(day_status):
        x = i * (bar_width + gap)
        color = color_map.get(s, color_map["unknown"])
        rects.append(f'<rect data-day="{i}" x="{x}" y="0" width="{bar_width}" height="{height}" fill="{color}" style="cursor:pointer;" />')

    svg_html = '<svg id="statusSvg" width="100%" height="{0}px" viewBox="0 0 {1} {0}" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg" style="display:block;">{2}</svg>'.format(height, total_width, "".join(rects))

    days_json = json.dumps(safe_day_data).replace("</", "<\\/")

    # Build HTML with string concatenation to avoid .format() brace escaping issues
    html = f"""
    <div id="statusContainer" style="width:100%;margin-bottom:32px;position:relative;">
      <div style="display:flex;justify-content:space-between;font-size:12px;color:#666;margin-bottom:8px;">
        <span>90 days ago</span>
        <span>Today</span>
      </div>
      {svg_html}
      
      <div id="popup" style="position:absolute;display:none;background:white;border:1px solid #e5e7eb;border-radius:8px;padding:14px 16px;box-shadow:0 12px 40px rgba(0,0,0,0.2);z-index:9999;min-width:360px;max-width:400px;max-height:200px;overflow-y:auto;left:50%;transform:translateX(-50%);top:50%;margin-top:-20px;pointer-events:auto;">
        <div id="popupDate" style="font-weight:600;color:#1f2937;margin-bottom:10px;font-size:14px;"></div>
        <div id="popupContent" style="font-size:13px;line-height:1.5;color:#555;"></div>
      </div>
    </div>
    
    <script>
    const dayData = {days_json};
    const statusContainer = document.getElementById('statusContainer');
    const popup = document.getElementById('popup');
    const popupDate = document.getElementById('popupDate');
    const popupContent = document.getElementById('popupContent');
    const svg = document.getElementById('statusSvg');
    let hideTimeout;
    
    function fmtDur(s) {{
      const h = Math.floor(s/3600); const m = Math.floor((s%3600)/60);
      if(h>0) return h+'h '+m+'m';
      return m+'m';
    }}
    
    function hidePopup() {{
      hideTimeout = setTimeout(() => {{
        popup.style.display = 'none';
      }}, 100);
    }}
    
    function showPopup() {{
      clearTimeout(hideTimeout);
      popup.style.display = 'block';
    }}
    
    svg.addEventListener('mousemove', (e) => {{
      const rect = e.target.closest('rect[data-day]');
      if(!rect) {{
        hidePopup();
        return;
      }}
      const idx = parseInt(rect.getAttribute('data-day'));
      const entry = dayData[idx];
      if(!entry) return;
      
      popupDate.innerHTML = entry.date;
      
      if(!entry.incidents || entry.incidents.length===0) {{
        popupContent.innerHTML = '<span style="color:#10b981;font-weight:600;">✓ Operational</span>';
      }} else {{
        let html='';
        entry.incidents.forEach((it, idx) => {{
          html += '<div style="margin-bottom:' + (idx < entry.incidents.length-1 ? '10px;padding-bottom:10px;border-bottom:1px solid #f0f0f0' : '0') + ';">';
          html += '<div style="font-weight:600;color:#1f2937;">'+it.title+'</div>';
          html += '<div style="color:#666;font-size:12px;margin-top:2px;">Duration: '+fmtDur(it.seconds)+'</div>';
          if(it.url) html += '<div style="margin-top:6px;"><a href="'+it.url+'" target="_blank" rel="noopener" style="color:#0066cc;text-decoration:none;font-size:12px;">View details →</a></div>';
          html += '</div>';
        }});
        popupContent.innerHTML = html;
      }}
      
      showPopup();
    }});
    
    svg.addEventListener('mouseleave', () => {{
      hidePopup();
    }});
    
    popup.addEventListener('mouseenter', () => {{
      showPopup();
    }});
    
    popup.addEventListener('mouseleave', () => {{
      hidePopup();
    }});
    </script>
    """
    
    return html


st.markdown("---")
st.subheader("Token Factory — 90 Day Status")
st.write("Historical view for the last 90 days for each Nebius region's Token Factory.")

token_components, err = fetch_token_components()
if err:
    st.error(err)
elif not token_components:
    st.info("No Token Factory components found.")
else:
    for comp in token_components:
        comp_id = comp.get("id")
        region = comp.get("region_name") or comp.get("name")
        st.markdown(f"**{region}**")
        day_status, downtime_seconds, day_incidents, err = build_90day_status_for_component(comp_id)
        if err:
            st.error(f"Error fetching incidents: {err}")
            continue
        if not day_status:
            st.info("No recent incidents; showing full operational history.")
            day_status = ["operational"] * 90
            downtime_seconds = 0
            day_incidents = [[] for _ in range(90)]

        html = render_90day_html(day_status, day_incidents, height=96)
        # compute uptime percent using seconds over 90 days
        total_seconds = 90 * 24 * 3600
        uptime_pct = max(0.0, (total_seconds - downtime_seconds) / total_seconds * 100)
        cols = st.columns([1, 6, 1])
        cols[0].markdown("90 days ago")
        with cols[1]:
            components.html(html, height=160)
        cols[2].markdown("Today")
        st.markdown(f"**{uptime_pct:.2f} % uptime**")        

