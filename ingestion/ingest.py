"""
Fetches actual + predicted water levels from NOAA CO-OPS API
for The Battery (station 8518750), computes surge, writes to
DynamoDB, and regenerates the S3 plot.
"""

#importing necessary libraries
import logging 
import requests
import boto3
import botocore
import matplotlib.pyplot as plt
from datetime import datetime, timedelta, timezone

#Logging configuration
logging.basicConfig(level=logging.INFO,format='%(asctime)s - %(levelname)s - %(message)s') # configures the ROOT logging system
log = logging.getLogger("surgewatch")#gets a named logger From that system

#Constants
NOAA_API_URL = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
STATION_ID = "8518750"  # The Battery, NY
TABLE_NAME = "surgewatch-readings"
BUCKET_NAME = "surgewatch-ds5220"

#AWS Clients
dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
table= dynamodb.Table(TABLE_NAME)
s3 = boto3.client('s3', region_name='us-east-1')

#Ingestion function
def fetch_noaa_data(product):
    params = {
    "station": STATION_ID,
    "product": product,  # passed in as argument
    "date": "latest",
    "datum": "MLLW",
    "time_zone": "gmt",
    "units": "english",
    "format": "json"
}
    try:
       log.info(f"Fetching {product} data for station {STATION_ID}")
       response = requests.get(NOAA_API_URL, params=params,timeout=10)
       response.raise_for_status()  # raises exception if 4xx or 5xx
       log.info(f"Successfully fetched {product} data")
       return response.json()
    except requests.exceptions.Timeout:
        log.error(f"NOAA API timed out fetching {product}")
        return None
    except requests.exceptions.HTTPError as e:
        log.error(f"NOAA API returned HTTP error for {product}: {e}")
        return None
    except requests.exceptions.RequestException as e:
        log.error(f"Network error fetching {product}: {e}")
        return None
    except Exception as e:
        log.error(f"Unexpected error fetching {product}: {e}")
        return None

def parse_reading(response: dict) -> tuple:
    try:
        log.info("Parsing NOAA response")
        
        # NOAA uses "data" for water_level but "predictions" for predictions
        records = response.get("data") or response.get("predictions")
        
        if not records:
            log.error("No data or predictions key found in response")
            return None, None
            
        timestamp = records[0]["t"]
        value = float(records[0]["v"])
        log.info(f"Parsed reading — timestamp: {timestamp}, value: {value}")
        return timestamp, value
        
    except (KeyError, IndexError, ValueError) as e:
        log.error(f"Failed to parse NOAA response: {e}")
        return None, None
    except Exception as e:
        log.error(f"Unexpected error parsing response: {e}")
        return None, None

def write_to_dynamodb(timestamp, actual, predicted, surge):
    """
    Writes a single tide reading to DynamoDB.
    """
    try:
        log.info(f"Writing record to DynamoDB — timestamp: {timestamp}, surge: {surge}")
        table.put_item(Item={
            "station_id": STATION_ID,
            "timestamp": timestamp,
            "actual": str(actual),
            "predicted": str(predicted),
            "surge": str(surge),
            "ingested_at":datetime.now(timezone.utc).isoformat()
        })
        log.info("Successfully wrote record to DynamoDB")
    except botocore.exceptions.ClientError as e:
        log.error(f"DynamoDB write failed: {e.response['Error']['Message']}")
    except Exception as e:
        log.error(f"Unexpected error writing to DynamoDB: {e}")



def generate_and_upload_plot():
    """
    Queries DynamoDB for recent readings, generates a 
    matplotlib chart of actual vs predicted water levels,
    and uploads it to S3 as latest.png
    """
    try:
        log.info("Querying DynamoDB for recent readings")
        
        # calculate timestamp from 48 hours ago
        since = (datetime.now(timezone.utc) - timedelta(hours=48)).strftime("%Y-%m-%d %H:%M")
        
        # query DynamoDB for readings since that timestamp
        response = table.query(
            KeyConditionExpression=boto3.dynamodb.conditions.Key("station_id").eq(STATION_ID) &
                boto3.dynamodb.conditions.Key("timestamp").gt(since),
        )
        
        items = response.get("Items", [])
        log.info(f"Retrieved {len(items)} records from DynamoDB")
        
        if len(items) < 2:
            log.warning("Not enough data to generate plot")
            return
        
        # sort by timestamp and extract values
        items.sort(key=lambda x: x["timestamp"])
        timestamps = [item["timestamp"] for item in items]
        actual     = [float(item["actual"]) for item in items]
        predicted  = [float(item["predicted"]) for item in items]
        surge      = [float(item["surge"]) for item in items]

        # build the plot
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))
        fig.suptitle("The Battery, NYC — Water Level & Surge", fontsize=14)

        # top chart — actual vs predicted
        ax1.plot(timestamps, actual, color="steelblue", label="Actual", linewidth=2)
        ax1.plot(timestamps, predicted, color="orange", linestyle="--", label="Predicted", linewidth=2)
        ax1.fill_between(timestamps, actual, predicted, alpha=0.2, color="red", label="Surge")
        ax1.set_ylabel("Water Level (ft)")
        ax1.legend()
        ax1.set_xticks([])
        ax1.grid(True, alpha=0.3)

        # bottom chart — surge only
        ax2.plot(timestamps, surge, color="red", linewidth=2)
        ax2.axhline(y=0, color="black", linestyle="-", linewidth=0.5)
        ax2.fill_between(timestamps, surge, 0, alpha=0.3, color="red")
        ax2.set_ylabel("Surge (ft)")
        ax2.set_xlabel("Time (UTC)")
        ax2.grid(True, alpha=0.3)

        # only show every 10th timestamp label
        tick_indices = list(range(0, len(timestamps), max(1, len(timestamps)//10)))
        ax2.set_xticks(tick_indices)
        ax2.set_xticklabels([timestamps[i] for i in tick_indices], rotation=45, ha="right")

        plt.tight_layout()

        # save to a temp file
        tmp_path = "/tmp/latest.png"
        plt.savefig(tmp_path, dpi=100, bbox_inches="tight")
        plt.close()
        log.info("Plot generated successfully")

        # upload to S3
        log.info(f"Uploading plot to S3 bucket {BUCKET_NAME}")
        s3.upload_file(
            tmp_path,
            BUCKET_NAME,
            "latest.png",
            ExtraArgs={"ContentType": "image/png"}
        )
        log.info("Plot uploaded to S3 successfully")

    except botocore.exceptions.ClientError as e:
        log.error(f"AWS error in generate_and_upload_plot: {e.response['Error']['Message']}")
    except Exception as e:
        log.error(f"Unexpected error generating plot: {e}")

def lambda_handler(event, context):
    """
    Main Lambda entry point. Called by EventBridge every 6 minutes.
    Fetches actual + predicted water levels, computes surge,
    writes to DynamoDB, and regenerates the S3 plot.
    """
    log.info("Surgewatch ingest run starting...")
    
    try:
        # 1. fetch actual water level
        actual_response = fetch_noaa_data("water_level")
        if actual_response is None:
            log.error("Failed to fetch actual water level — aborting run")
            return {"statusCode": 500, "body": "Failed to fetch actual"}
        
        # 2. fetch predicted water level
        predicted_response = fetch_noaa_data("predictions")
        if predicted_response is None:
            log.error("Failed to fetch predictions — aborting run")
            return {"statusCode": 500, "body": "Failed to fetch predictions"}
        
        # 3. parse both responses
        timestamp, actual = parse_reading(actual_response)
        _, predicted = parse_reading(predicted_response)
        
        if None in (timestamp, actual, predicted):
            log.error("Failed to parse one or more readings — aborting run")
            return {"statusCode": 500, "body": "Parse failed"}
        
        # 4. compute surge
        surge = round(actual - predicted, 3)
        log.info(f"Computed surge: {surge} ft (actual={actual}, predicted={predicted})")
        
        # 5. write to DynamoDB
        write_to_dynamodb(timestamp, actual, predicted, surge)
        
        # 6. regenerate plot
        generate_and_upload_plot()
        
        log.info("Surgewatch ingest run complete!")
        return {"statusCode": 200, "body": "Success"}

    except Exception as e:
        log.error(f"Unhandled error in lambda_handler: {e}")
        return {"statusCode": 500, "body": str(e)}
    

# local test — remove before deploying
if __name__ == "__main__":
    lambda_handler({}, {})