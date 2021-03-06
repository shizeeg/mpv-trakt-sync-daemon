import datetime
import json
import logging
import sys
import time

import os
import requests

import trakt_key_holder

log = logging.getLogger('mpvTraktSync')

LOCAL_STORAGE_JSON_FILE = './trakt_token.json'


def get_access_token():
    if not os.path.isfile(LOCAL_STORAGE_JSON_FILE):
        prompt_device_authentication()

    tokens = json.load(open(LOCAL_STORAGE_JSON_FILE))

    expire_date = datetime.datetime.utcfromtimestamp(
        tokens['created_at'] + tokens['expires_in'])
    remaining_time = expire_date - datetime.datetime.utcnow()

    # make sure the token is at least valid for the next day
    if remaining_time < datetime.timedelta(days=1):
        log.info('Token expired')
        token_refresh_request = requests.post('https://api.trakt.tv/oauth/token', json={
            'refresh_token': tokens['refresh_token'],
            'client_id': trakt_key_holder.get_id(),
            'client_secret': trakt_key_holder.get_secret(),
            'redirect_uri': 'urn:ietf:wg:oauth:2.0:oob',
            'grant_type': 'refresh_token'
        })

        if token_refresh_request.status_code == 200:
            log.info('Successfully refreshed token')
            # save response to local json file
            json.dump(token_refresh_request.json(),
                      open(LOCAL_STORAGE_JSON_FILE, 'w'))

            # reload new token
            tokens = json.load(open(LOCAL_STORAGE_JSON_FILE))
        else:
            sys.exit('Refreshing token failed with http code %d.\n%s' %
                     (token_refresh_request.status_code, token_refresh_request.text))
    return tokens['access_token']


def prompt_device_authentication():
    code_request = requests.post('https://api.trakt.tv/oauth/device/code', json={
        'client_id': trakt_key_holder.get_id()
    })

    if code_request.status_code == 200:
        code_json = code_request.json()
        print('Please visit %s and enter code %s to grant this app permission to your trakt account.' %
              (code_json['verification_url'], code_json['user_code']))
        start_time = datetime.datetime.now()
        got_access_token = False

        while datetime.datetime.now() - start_time < datetime.timedelta(seconds=code_json['expires_in']):
            time.sleep(code_json['interval'])
            token_request = requests.post('https://api.trakt.tv/oauth/device/token', json={
                'code': code_json['device_code'],
                'client_id': trakt_key_holder.get_id(),
                'client_secret': trakt_key_holder.get_secret()
            })
            if token_request.status_code == 200:
                token_json = token_request.json()
                json.dump(token_json, open(LOCAL_STORAGE_JSON_FILE, 'w'))
                log.info('\nSuccessfully established access to trakt account')
                got_access_token = True
                break
            else:
                print(str(token_request.status_code) + ' ', end='', flush=True)

        if not got_access_token:
            log.critical('Could not get access token. Please try again.')
            sys.exit(5)

    else:
        log.critical('POST request for generating device codes failed with HTTP code %d.\n%s',
                     code_request.status_code, code_request.text)
        sys.exit(6)


if __name__ == '__main__':
    get_access_token()
