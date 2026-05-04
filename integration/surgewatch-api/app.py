from chalice import Chalice
import boto3
import botocore
import logging
from datetime import datetime, timedelta, timezone

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger('surgewatch-api')

TABLE_NAME = 'surgewatch-readings'
STATION_ID = '8518750'
BUCKET_NAME = 'surgewatch-ds5220'

dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
table = dynamodb.Table(TABLE_NAME)

app = Chalice(app_name='surgewatch-api')

@app.route('/')
def index():
    return {
        'about': 'Tracks real-time water levels and storm surge at The Battery, NYC using NOAA tide gauge data.',
        'resources': ['current', 'trend', 'plot']
    }

@app.route('/current')
def current():
    try:
        log.info('Fetching most recent reading from DynamoDB')
        response = table.query(
            KeyConditionExpression=boto3.dynamodb.conditions.Key('station_id').eq(STATION_ID),
            ScanIndexForward=False,
            Limit=1
        )
        items = response.get('Items', [])
        if not items:
            log.warning('No items found in DynamoDB')
            return {'response': 'No data available yet.'}
        item = items[0]
        actual = float(item['actual'])
        predicted = float(item['predicted'])
        surge = float(item['surge'])
        timestamp = item['timestamp']
        log.info(f'Returning current reading: {timestamp}')
        return {
            'response': f'The Battery, NYC as of {timestamp} UTC: Water level {actual:.2f}ft (predicted {predicted:.2f}ft). Surge: {surge:+.3f}ft above predicted.'
        }
    except botocore.exceptions.ClientError as e:
        log.error(f'DynamoDB error in /current: {e.response["Error"]["Message"]}')
        return {'response': 'Error fetching current data.'}
    except Exception as e:
        log.error(f'Unexpected error in /current: {e}')
        return {'response': 'Unexpected error.'}

@app.route('/trend')
def trend():
    try:
        log.info('Fetching last 24 hours of readings for trend')
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime('%Y-%m-%d %H:%M')
        response = table.query(
            KeyConditionExpression=boto3.dynamodb.conditions.Key('station_id').eq(STATION_ID) &
                boto3.dynamodb.conditions.Key('timestamp').gt(since),
            ScanIndexForward=False
        )
        items = response.get('Items', [])
        log.info(f'Retrieved {len(items)} records for trend calculation')
        if len(items) < 2:
            return {'response': 'Not enough data yet for trend analysis.'}
        surges = [float(item['surge']) for item in items]
        avg_surge = round(sum(surges) / len(surges), 3)
        max_surge = round(max(surges), 3)
        min_surge = round(min(surges), 3)
        latest_surge = float(items[0]['surge'])
        oldest_surge = float(items[-1]['surge'])
        direction = 'rising' if latest_surge > oldest_surge else 'falling'
        log.info(f'Trend calculated: avg={avg_surge}, max={max_surge}, direction={direction}')
        return {
            'response': f'Last 24hrs at The Battery ({len(items)} readings): Avg surge {avg_surge:+.3f}ft, Max {max_surge:+.3f}ft, Min {min_surge:+.3f}ft. Surge is currently {direction}.'
        }
    except botocore.exceptions.ClientError as e:
        log.error(f'DynamoDB error in /trend: {e.response["Error"]["Message"]}')
        return {'response': 'Error fetching trend data.'}
    except Exception as e:
        log.error(f'Unexpected error in /trend: {e}')
        return {'response': 'Unexpected error.'}

@app.route('/plot')
def plot():
    try:
        log.info('Returning S3 plot URL')
        url = f'https://{BUCKET_NAME}.s3.amazonaws.com/latest.png'
        log.info(f'Plot URL: {url}')
        return {'response': url}
    except Exception as e:
        log.error(f'Unexpected error in /plot: {e}')
        return {'response': 'Error fetching plot URL.'}
