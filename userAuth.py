from twitchAPI.helper import build_url, build_scope, TWITCH_AUTH_BASE_URL, get_uuid
import requests

def authenticate(twitch, scopes):
    params = {
        'client_id': twitch.app_id,
        'redirect_uri': 'https://retrohollow.com/twitchAuth.php',
        'response_type': 'code',
        'scope': build_scope(scopes),
        'force_verify': 'false',
        'state': str(get_uuid())
    }
    print(f'Visit this URL and paste the code below: {build_url(TWITCH_AUTH_BASE_URL + "oauth2/authorize", params)}')
    user_token = input('Enter Code: ')
    params = {
        'client_id': twitch.app_id,
        'client_secret': twitch.app_secret,
        'code': user_token,
        'grant_type': 'authorization_code',
        'redirect_uri': 'https://retrohollow.com/twitchAuth.php'
    }
    url = build_url(TWITCH_AUTH_BASE_URL + 'oauth2/token', params)
    response = requests.post(url)
    data = response.json()
    print(data)
    return data['access_token'], data['refresh_token']
        