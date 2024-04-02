# calendarListener

A sensor that inspects the google calendar api to check for calendar events.
If the local time is during a calendar event, a message is sent to the
led-controller to enable a condition.  When there are no current calendar
events, the calendarListener disables the condition.


## Configuration

The `calendarListener` requires that a `config.yml` file be present. The file
contains a list of google accounts, the notification that will be sent to the
led-controller when a calendar event is current, and a list of calendars that
will be inspected.

A configuration file looks like:

```
- name: john.doe@example.com
  notification: PersonalCalendarEvent
  calendars:
    - john.doe@example.com
    - Work Related
```


## Credentials

The `calendarListener` requires that a `credentials.json` file be present.  It
is populated with the json representation of client secret used to authenticate
access to the google api.

The contents of a `credentials.json` file looks like:

```
{
    "web":{
        "client_id":"...",
        "project_id":"blinkstick",
        "auth_uri":"https://accounts.google.com/o/oauth2/auth",
        "token_uri":"https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url":"https://www.googleapis.com/oauth2/v1/certs",
        "client_secret":"...",
        "redirect_uris":["http://localhost:8080"],
        "javascript_origins":["http://localhost:8080"]
    }
}
```

## Google API

The calendar listener uses the `calendar.v3` api. Specifically the `calendar.v3.CalendarList.List` and `calendar.v3.Events.List` methods.  The google credentials must have these methods enabled.

In the worst case, one `calendar.v3.Events.List` call is made for every calendar for every account every minute.
