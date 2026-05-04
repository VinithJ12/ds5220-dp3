# Surgewatch — NYC Harbor Tide Surge Monitor

## Project Overview

Surgewatch is a serverless AWS data pipeline that continuously monitors 
water levels at The Battery tide gauge station in Lower Manhattan, NYC 
(NOAA Station 8518750). Every 6 minutes, it fetches real-time actual and 
predicted water level readings from the NOAA CO-OPS API, computes storm 
surge (the difference between actual and predicted levels), and stores the 
results in DynamoDB. A public REST API exposes current conditions, trend 
analysis, and a live visualization of the tidal cycle and surge patterns.

## Why This Data Matters

Storm surge is one of the most destructive forces in coastal flooding. 
When Hurricane Sandy struck NYC in 2012, The Battery recorded a surge of 
9.23 feet — the highest ever measured there — flooding subway tunnels, 
knocking out power, and causing billions in damage. 

Surgewatch tracks this same signal in real time. By continuously comparing 
actual water levels against NOAA's astronomical predictions, it detects 
when meteorological forces (wind, pressure systems, storms) are pushing 
water above or below expected levels. A persistent positive surge can be 
an early warning sign of coastal flooding risk.

This data is valuable to:
- **Emergency managers** monitoring flood risk in real time
- **Climate researchers** studying sea level rise trends over time  
- **City planners** designing resilient coastal infrastructure
- **The general public** understanding how weather affects their waterfront

## Architecture

### Part 1 — Ingestion Pipeline
A CloudWatch/EventBridge scheduled rule fires every 6 minutes, triggering 
an AWS Lambda function. The Lambda fetches both actual and predicted water 
level readings from the NOAA CO-OPS API, computes surge, writes a 
timestamped record to DynamoDB, and regenerates a matplotlib chart 
uploaded to a public S3 bucket.

EventBridge (rate 6 min)
→ Ingest Lambda
→ NOAA CO-OPS API (actual + predicted)
→ DynamoDB (write timestamped record)
→ S3 (regenerate latest.png plot)

### Part 2 — Integration API
A Chalice app deployed to AWS Lambda + API Gateway exposes three public 
endpoints that read from the DynamoDB table populated by Part 1.

Discord Bot / Browser
→ API Gateway
→ Chalice Lambda
→ DynamoDB (query readings)
→ S3 URL (for /plot)

### AWS Resources Used
| Resource | Purpose |
|---|---|
| AWS Lambda | Runs ingest function + serves API |
| EventBridge | Triggers ingest Lambda every 6 minutes |
| DynamoDB | Stores timestamped tide readings |
| S3 | Hosts public plot PNG |
| API Gateway | Routes HTTP requests to Chalice Lambda |
| IAM | Controls permissions between services |
| CloudWatch | Stores Lambda logs for monitoring |

## Storage Schema

### DynamoDB Table: `surgewatch-readings`

| Field | Type | Description |
|---|---|---|
| `station_id` | String (Partition Key) | NOAA station ID — `8518750` for The Battery |
| `timestamp` | String (Sort Key) | Reading time in UTC — `2026-05-04 15:18` |
| `actual` | String | Actual water level in feet (MLLW datum) |
| `predicted` | String | NOAA predicted water level in feet |
| `surge` | String | Computed surge = actual − predicted (feet) |
| `ingested_at` | String | ISO timestamp when Lambda wrote the record |

### Why This Schema?

The partition key `station_id` groups all readings by station — making 
it trivial to add a second station (e.g. Sandy Hook) later. The sort key 
`timestamp` keeps records ordered chronologically, so querying "last 24 
hours" is a fast, efficient range query rather than a full table scan.

Values are stored as strings to avoid DynamoDB Decimal serialization 
issues when returning JSON from the API.

### Cadence
- **Sampling rate:** every 6 minutes (matches NOAA sensor update frequency)
- **Retention:** all records kept indefinitely

## API Resources

Base URL: `https://1de7tewweh.execute-api.us-east-1.amazonaws.com/api`

> Note: This API is live and callable from the course Discord bot 
> using `/project surgewatch`

### `GET /`
Returns project description and list of available resources.
```json
{
  "about": "Tracks real-time water levels and storm surge at The Battery, NYC using NOAA tide gauge data.",
  "resources": ["current", "trend", "plot"]
}
```

### `GET /current`
Returns the most recent tide reading from DynamoDB including actual 
water level, predicted level, and computed surge.

**Example response:**
```json
{
  "response": "The Battery, NYC as of 2026-05-04 21:12 UTC: Water level 0.93ft (predicted 0.75ft). Surge: +0.174ft above predicted."
}
```

### `GET /trend`
Returns surge trend analysis over the last 24 hours — average, 
maximum, minimum surge, and current direction (rising/falling).

**Example response:**
```json
{
  "response": "Last 24hrs at The Battery (54 readings): Avg surge -0.148ft, Max +0.251ft, Min -0.455ft. Surge is currently falling."
}
```

### `GET /plot`
Returns the public S3 URL of the latest matplotlib chart showing 
actual vs predicted water levels and surge over the last 48 hours.

**Example response:**
```json
{
  "response": "https://surgewatch-ds5220.s3.amazonaws.com/latest.png"
}
```
