#!/usr/bin/env python3
"""
District Statistics Dashboard
Sag Harbor UFSD - No API key required
Collects from Google Workspace, JAMF, and eSchool
then generates HTML widget for Google Sites and Smart Schools
"""

import json
import os
import requests
import urllib3
from datetime import datetime, timezone
from urllib.parse import quote
from google.oauth2 import service_account
from googleapiclient.discovery import build

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ============================================================
# CONFIGURATION - UPDATE THESE VALUES
# ============================================================

# Google Workspace
GOOGLE_SERVICE_ACCOUNT_FILE = os.environ.get('GOOGLE_SERVICE_ACCOUNT_FILE', '/Users/vchiuchiolo/Documents/API/live-user-counts.json')
GOOGLE_ADMIN_EMAIL = os.environ.get('GOOGLE_ADMIN_EMAIL', 'YOUR-ADMIN-EMAIL@sagharborschools.org')
STAFF_OU = '/users/employees'
STUDENT_OU = '/users/students'
CHROMEBOOK_OU = '/chromebooks/2025 chromebooks'

# JAMF
JAMF_URL = "https://shmac02.shsd.sagharborschools.org:8443"
JAMF_CLIENT_ID = os.environ.get('JAMF_CLIENT_ID', 'YOUR-JAMF-CLIENT-ID')
JAMF_CLIENT_SECRET = os.environ.get('JAMF_CLIENT_SECRET', 'YOUR-JAMF-SECRET')

# eSchool
ESCHOOL_TOKEN_URL = "https://guru.eschooldata.com/api/v1/auth/token"
ESCHOOL_BASE_URL = "https://guru.eschooldata.com/api"
ESCHOOL_CLIENT_ID = os.environ.get('ESCHOOL_CLIENT_ID', '4b12128c-5683-4d3a-8550-1c30912657d8.guru.eschooldata.com/api')
ESCHOOL_CLIENT_SECRET = os.environ.get('ESCHOOL_CLIENT_SECRET', '')

# Output paths
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
WIDGET_PATH = os.path.join(OUTPUT_DIR, 'district_stats_widget.html')
DATA_PATH = os.path.join(OUTPUT_DIR, 'district_stats.json')

# ============================================================
# DATA COLLECTION - GOOGLE WORKSPACE
# ============================================================

def collect_google_data():
    print("\n[Google Workspace] Collecting data...")
    try:
        SCOPES = [
            'https://www.googleapis.com/auth/admin.directory.user.readonly',
            'https://www.googleapis.com/auth/admin.directory.device.chromeos.readonly',
            'https://www.googleapis.com/auth/admin.directory.orgunit.readonly'
        ]
        credentials = service_account.Credentials.from_service_account_file(
            GOOGLE_SERVICE_ACCOUNT_FILE, scopes=SCOPES, subject=GOOGLE_ADMIN_EMAIL
        )
        service = build('admin', 'directory_v1', credentials=credentials)

        def count_users(ou):
            all_users = []
            page_token = None
            while True:
                params = {'customer': 'my_customer', 'query': f"orgUnitPath='{ou}'", 'maxResults': 500}
                if page_token:
                    params['pageToken'] = page_token
                results = service.users().list(**params).execute()
                all_users.extend(results.get('users', []))
                page_token = results.get('nextPageToken')
                if not page_token:
                    break
            return len([u for u in all_users if not u.get('suspended', False)])

        def count_chromebooks(ou):
            all_devices = []
            page_token = None
            while True:
                params = {'customerId': 'my_customer', 'orgUnitPath': ou, 'maxResults': 500}
                if page_token:
                    params['pageToken'] = page_token
                results = service.chromeosdevices().list(**params).execute()
                all_devices.extend(results.get('chromeosdevices', []))
                page_token = results.get('nextPageToken')
                if not page_token:
                    break
            return len([d for d in all_devices if d.get('status') == 'ACTIVE'])

        staff = count_users(STAFF_OU)
        students = count_users(STUDENT_OU)
        chromebooks = count_chromebooks(CHROMEBOOK_OU)

        print(f"  ✓ Staff: {staff} | Students: {students} | Chromebooks: {chromebooks}")
        return {'staff': staff, 'students': students, 'chromebooks': chromebooks, 'error': None}

    except Exception as e:
        print(f"  ✗ Error: {e}")
        return {'staff': 0, 'students': 0, 'chromebooks': 0, 'error': str(e)}

# ============================================================
# DATA COLLECTION - JAMF
# ============================================================

def collect_jamf_data():
    print("\n[JAMF] Collecting data...")
    try:
        # Send credentials as form data (not Basic Auth)
        response = requests.post(
            f"{JAMF_URL}/api/oauth/token",
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            data={
                'grant_type': 'client_credentials',
                'client_id': JAMF_CLIENT_ID,
                'client_secret': JAMF_CLIENT_SECRET
            },
            verify=False,
            timeout=10
        )
        print(f"  JAMF auth status: {response.status_code}")
        token = response.json().get('access_token')
        if not token:
            print(f"  ✗ No token received: {response.text[:200]}")
            return {'macs': 0, 'ipads': 0, 'error': 'No token'}
        headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json'}

        computers = requests.get(f"{JAMF_URL}/JSSResource/computers", headers=headers, verify=False, timeout=10)
        mac_count = len(computers.json().get('computers', []))

        mobiles = requests.get(f"{JAMF_URL}/JSSResource/mobiledevices", headers=headers, verify=False, timeout=10)
        ipad_count = len(mobiles.json().get('mobile_devices', []))

        print(f"  ✓ Macs: {mac_count} | iPads: {ipad_count}")
        return {'macs': mac_count, 'ipads': ipad_count, 'error': None}

    except Exception as e:
        print(f"  ✗ Error: {e}")
        return {'macs': 0, 'ipads': 0, 'error': str(e)}

# ============================================================
# DATA COLLECTION - ESCHOOL
# ============================================================

def collect_eschool_data():
    print("\n[eSchool] Collecting data...")
    try:
        encoded_id = quote(ESCHOOL_CLIENT_ID, safe='')
        encoded_secret = quote(ESCHOOL_CLIENT_SECRET, safe='')
        form_data = f"grant_type=client_credentials&client_id={encoded_id}&client_secret={encoded_secret}"

        response = requests.post(
            ESCHOOL_TOKEN_URL,
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            data=form_data,
            verify=False,
            timeout=10
        )
        token = response.json().get('access_token')
        headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json'}

        # Student count
        students_response = requests.get(
            f"{ESCHOOL_BASE_URL}/v1/students",
            headers=headers,
            params={'pageNo': 1, 'pageSize': 1},
            verify=False,
            timeout=10
        )
        student_count = students_response.json().get('pagingInfo', {}).get('totalCount', 0)

        # Staff count
        staff_count = 0
        for endpoint in ['staff', 'employees', 'personnel']:
            try:
                r = requests.get(
                    f"{ESCHOOL_BASE_URL}/v1/{endpoint}",
                    headers=headers,
                    params={'pageNo': 1, 'pageSize': 1},
                    verify=False,
                    timeout=10
                )
                if r.status_code == 200:
                    staff_count = r.json().get('pagingInfo', {}).get('totalCount', 0)
                    if staff_count:
                        break
            except Exception:
                continue

        print(f"  ✓ Students: {student_count} | Staff: {staff_count}")
        return {'students': student_count, 'staff': staff_count, 'error': None}

    except Exception as e:
        print(f"  ✗ Error: {e}")
        return {'students': 0, 'staff': 0, 'error': str(e)}

# ============================================================
# AGGREGATION - Pure Python, no API needed
# ============================================================

def aggregate_data(google, jamf, eschool):
    print("\n[Aggregation] Calculating final stats...")

    # Clear rules - no ambiguity, no AI needed:
    # Students  = eSchool (official enrollment, fallback to Google)
    # Staff     = Google Workspace (most current active accounts)
    # Chromebooks = Google Workspace
    # Macs      = JAMF
    # iPads     = JAMF

    students   = eschool['students'] if eschool['students'] > 0 else google['students']
    staff      = google['staff']
    chromebooks = google['chromebooks']
    macs       = jamf['macs']
    ipads      = jamf['ipads']
    total_devices = chromebooks + macs + ipads

    # Log any discrepancies worth noting
    notes = []
    if eschool['students'] > 0 and google['students'] > 0:
        diff = abs(eschool['students'] - google['students'])
        if diff > 10:
            notes.append(f"Student count differs by {diff} between eSchool ({eschool['students']}) and Google ({google['students']})")

    stats = {
        'total_students': students,
        'total_staff': staff,
        'chromebooks': chromebooks,
        'mac_computers': macs,
        'ipads': ipads,
        'total_devices': total_devices,
        'notes': notes
    }

    print(f"  ✓ Students:     {students:,}")
    print(f"  ✓ Staff:        {staff:,}")
    print(f"  ✓ Chromebooks:  {chromebooks:,}")
    print(f"  ✓ Macs:         {macs:,}")
    print(f"  ✓ iPads:        {ipads:,}")
    print(f"  ✓ Total Devices:{total_devices:,}")
    if notes:
        for note in notes:
            print(f"  ⚠ {note}")

    return stats

# ============================================================
# HTML WIDGET
# ============================================================

def generate_widget(stats):
    print("\n[Widget] Generating HTML...")
    ny_time = datetime.now(ZoneInfo("America/New_York"))
    updated = ny_time.now().strftime('%B %d, %Y at %I:%M %p')

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="refresh" content="3600">
<title>Sag Harbor UFSD - District Statistics</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&family=DM+Serif+Display&display=swap" rel="stylesheet">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: 'DM Sans', sans-serif; background: transparent; padding: 20px; }}

  .stats-container {{
    background: linear-gradient(135deg, #890204 0%, #890204 100%);
    border-radius: 16px;
    padding: 32px;
    color: white;
    max-width: 900px;
    margin: 0 auto;
    box-shadow: 0 20px 60px rgba(0,0,0,0.3);
  }}

  .stats-header {{
    text-align: center;
    margin-bottom: 28px;
    padding-bottom: 20px;
    border-bottom: 1px solid rgba(255,255,255,0.15);
  }}

  .stats-title {{
    font-family: 'DM Serif Display', serif;
    font-size: 26px;
    font-weight: 400;
    margin-bottom: 4px;
  }}

  .stats-subtitle {{
    font-size: 12px;
    opacity: 0.5;
    letter-spacing: 2px;
    text-transform: uppercase;
  }}

  .stats-grid {{
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 16px;
    margin-bottom: 24px;
  }}

  .stat-card {{
    background: rgba(255,255,255,0.08);
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 12px;
    padding: 22px 16px;
    text-align: center;
    animation: fadeInUp 0.5s ease both;
  }}

  .stat-card:nth-child(1) {{ animation-delay: 0.1s; }}
  .stat-card:nth-child(2) {{ animation-delay: 0.2s; }}
  .stat-card:nth-child(3) {{ animation-delay: 0.3s; }}

  .stat-icon {{ font-size: 22px; margin-bottom: 10px; display: block; }}

  .stat-number {{
    font-size: 38px;
    font-weight: 700;
    line-height: 1;
    margin-bottom: 6px;
    background: linear-gradient(135deg, #ffffff, #ffffff);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
  }}

  .stat-label {{
    font-size: 11px;
    opacity: 0.6;
    letter-spacing: 1.5px;
    text-transform: uppercase;
  }}

  .divider-label {{
    font-size: 11px;
    opacity: 0.4;
    letter-spacing: 2px;
    text-transform: uppercase;
    text-align: center;
    margin-bottom: 14px;
  }}

  .devices-grid {{
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 12px;
  }}

  .device-card {{
    background: rgba(255,255,255,0.05);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 10px;
    padding: 16px 12px;
    text-align: center;
    animation: fadeInUp 0.5s ease both;
  }}

  .device-card:nth-child(1) {{ animation-delay: 0.4s; }}
  .device-card:nth-child(2) {{ animation-delay: 0.5s; }}
  .device-card:nth-child(3) {{ animation-delay: 0.6s; }}

  .device-number {{
    font-size: 28px;
    font-weight: 700;
    background: linear-gradient(135deg, #ffffff, #ffffff);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    line-height: 1;
    margin-bottom: 5px;
  }}

  .device-icon {{ font-size: 18px; margin-bottom: 6px; display: block; }}

  .device-label {{
    font-size: 11px;
    opacity: 0.55;
    letter-spacing: 1px;
    text-transform: uppercase;
  }}

  .stats-footer {{
    text-align: center;
    margin-top: 20px;
    padding-top: 16px;
    border-top: 1px solid rgba(255,255,255,0.1);
    font-size: 11px;
    opacity: 0.35;
  }}

  @keyframes fadeInUp {{
    from {{ opacity: 0; transform: translateY(14px); }}
    to {{ opacity: 1; transform: translateY(0); }}
  }}

  @media (max-width: 480px) {{
    .stats-grid {{ grid-template-columns: repeat(2, 1fr); }}
    .stat-number {{ font-size: 30px; }}
    .devices-grid {{ grid-template-columns: repeat(2, 1fr); }}
  }}
</style>
</head>
<body>
<div class="stats-container">
  <div class="stats-header">
    <div class="stats-title">Sag Harbor Union Free School District</div>
    <div class="stats-subtitle">District at a Glance</div>
  </div>

  <div class="stats-grid">
    <div class="stat-card">
      <span class="stat-icon">🎓</span>
      <div class="stat-number">{stats['total_students']:,}</div>
      <div class="stat-label">Students</div>
    </div>
    <div class="stat-card">
      <span class="stat-icon">👩‍🏫</span>
      <div class="stat-number">{stats['total_staff']:,}</div>
      <div class="stat-label">Staff</div>
    </div>
    <div class="stat-card">
      <span class="stat-icon">💻</span>
      <div class="stat-number">{stats['total_devices']:,}</div>
      <div class="stat-label">Total Devices</div>
    </div>
  </div>

  <div class="divider-label">Device Breakdown</div>
  <div class="devices-grid">
    <div class="device-card">
      <span class="device-icon">🟡</span>
      <div class="device-number">{stats['chromebooks']:,}</div>
      <div class="device-label">Chromebooks</div>
    </div>
    <div class="device-card">
      <span class="device-icon">🍎</span>
      <div class="device-number">{stats['mac_computers']:,}</div>
      <div class="device-label">Mac Computers</div>
    </div>
    <div class="device-card">
      <span class="device-icon">📱</span>
      <div class="device-number">{stats['ipads']:,}</div>
      <div class="device-label">iPads</div>
    </div>
  </div>

  <div class="stats-footer">
    Last updated: {updated} &nbsp;·&nbsp; Auto-refreshes hourly
  </div>
</div>
</body>
</html>"""

    with open(WIDGET_PATH, 'w') as f:
        f.write(html)

    print(f"  ✓ Widget saved to: {WIDGET_PATH}")

# ============================================================
# MAIN
# ============================================================

def main():
    print("="*60)
    print("Sag Harbor UFSD - District Statistics Update")
    print(f"Started: {ny_time.now().strftime('%B %d, %Y at %I:%M %p')}")
    print("="*60)

    # Collect from all sources
    google_data   = collect_google_data()
    jamf_data     = collect_jamf_data()
    eschool_data  = collect_eschool_data()

    # Aggregate with pure Python
    stats = aggregate_data(google_data, jamf_data, eschool_data)

    # Save raw data for reference
    full_data = {
        'timestamp': datetime.now().isoformat(),
        'aggregated': stats,
        'raw': {
            'google': google_data,
            'jamf': jamf_data,
            'eschool': eschool_data
        }
    }
    with open(DATA_PATH, 'w') as f:
        json.dump(full_data, f, indent=2)
    print(f"\n[Data] Raw data saved to: {DATA_PATH}")

    # Generate widget
    generate_widget(stats)

    print("\n" + "="*60)
    print("✓ All done!")
    print(f"  Widget → {WIDGET_PATH}")
    print(f"  Data   → {DATA_PATH}")
    print("="*60)

if __name__ == '__main__':
    main()
