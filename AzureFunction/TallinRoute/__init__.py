# -----------------------------------------------------------
# Azure Functions to generate N numbers of random route destinations 
# Timer trigger: configured to run every hour
# Blob storage output: will save result as a CSV in a blob container
#
# City : Tallinn
# -----------------------------------------------------------

import datetime
import logging
import os

import azure.functions as func
import pandas as pd
import numpy as np
import requests
import json


#Coordinates points around city of interest
maxLatitude = 59.443247
minLatitude = 59.424395
maxLongitude = 24.785602
minLongitude = 24.715832
#Number of road destinations to compute
nb = 100
#Azure Maps subscription key as environment variable
subscriptionKey = os.environ["AZURE_MAPS_KEY"]


def getLatitudes(minLatitude, maxLatitude, nb):
    """Generates nb numbers of latitudes"""
    latitudeRange = [minLatitude, maxLatitude]
    meanLatitude = np.mean(latitudeRange)
    #Generate random latitudes with more concentration in the city center
    latitudes = np.random.normal(meanLatitude, (maxLatitude-minLatitude)/2, nb)
    return latitudes


def getLongitudes(minLongitude, maxLongitude, nb):
    """Generates nb numbers of longitudes"""
    longitudeRange = [minLongitude, maxLongitude]
    meanLongitude = np.mean(longitudeRange)
    #Generate random longitudes with more concentration in the city center
    longitudes = np.random.normal(meanLongitude, (maxLongitude-minLongitude)/2, nb)
    return longitudes


def getCoordinates(minLatitude, maxLatitude, minLongitude, maxLongitude, nb):
    """Generates a nbx2 matrix of latitude-longitude pairs"""
    latitudes = getLatitudes(minLatitude, maxLatitude, nb)
    longitudes = getLongitudes(minLongitude, maxLongitude, nb)
    coordinates = np.column_stack((latitudes, longitudes))
    return coordinates


def getQueries(departureCoordinates, arrivalCoordinates):
    """Generates batch of route direction queries"""
    #initiate POST request call body
    body = {
        "batchItems": [
        ]
    }

    #Create a query for each coordinate pair
    for dc, ac in zip(departureCoordinates, arrivalCoordinates):
        query = '{"query": "?query=' + str(dc[0]) + ',' + str(dc[1]) + ':' + str(ac[0]) + ',' + str(ac[1]) + '&travelMode=taxi&traffic=true&computeTravelTimeFor=all"}'
        q = json.loads(query)
        body['batchItems'].append(q)

    return body

def getHeaders():
    """Generates POST request headers"""
    header = {
    'Content-type': 'application/json'
    }
    return header

def getResultDataFrame(result):
    """Save summary results as a dataframe"""
    df = pd.DataFrame()
    for direction in result['batchItems']:
        if 'routes' in direction['response']:
            for route in direction['response']['routes']:
                data = pd.DataFrame.from_dict(route['summary'], orient='index').T
                df = df.append(data)
        else :
            logging.warning("'Routes' parameter missing in the payload")

    df = df.reset_index(drop=True)
    return df


def main(mytimer: func.TimerRequest, outputBlob: func.Out[func.InputStream]) -> None:
    utc_timestamp = datetime.datetime.utcnow().replace(
        tzinfo=datetime.timezone.utc).isoformat()

    if mytimer.past_due:
        logging.info('The timer is past due!')

    logging.info('Python timer trigger function ran at %s', utc_timestamp)

    departureCoordinates = getCoordinates(minLatitude, maxLatitude, minLongitude, maxLongitude, nb)
    arrivalCoordinates = getCoordinates(minLatitude, maxLatitude, minLongitude, maxLongitude, nb)

    logging.info('Coordinates calculated')

    url = f'https://atlas.microsoft.com/route/directions/batch/sync/json?api-version=1.0&subscription-key={subscriptionKey}'

    logging.info('Calling: %s', url)

    body = getQueries(departureCoordinates, arrivalCoordinates)

    header = getHeaders()

    r = requests.post(url, json=body, headers=header)

    status_code = r.status_code

    logging.info('Azure Maps API called with status code %d', status_code)

    if status_code == 200:

        result = r.json()

        df = getResultDataFrame(result)

        #Add query coordinates to the result
        dfDC = pd.DataFrame(departureCoordinates, columns=["departureLatitude", "departureLongitude"])
        dfAC = pd.DataFrame(arrivalCoordinates, columns=["arrivalLatitude", "arrivalLongitude"])
        df = df.join(dfDC).join(dfAC)

        logging.info('Route data collected. Itinerary departure time: %s', df.departureTime[0])

        #Save result as a dataframe in the configured blob storage
        file = df.to_csv(index=False)

        outputBlob.set(file)

        logging.info('CSV file sent to Blob.')
    
    else:
        try :
            r.raise_for_status()
        except requests.exceptions.HTTPError as e: 
            logging.error("HTTP error occured: %s", e)