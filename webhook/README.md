# webhook

Listens for alerts raised by `prometheus` via `alertmanager`.  Matches alerts
by label and value and maps them to conditions in the `led-manager`.  For
alerts that do not match a defined label/value pair, a default condition is
raised in the `led-manager`.

The `webhook` sensor is useful for providing self diagnostics for the
blinkstick-notifier deployment.  In particular, regresh tokens can regularly
expire based on an organization's security policies.  Informing the uesr that
their google calendar cannot be checked for current events will prompt the user
to fix their configuration or risk not being informed of current meetings.

## Configuration

A configuration file looks like:

```
defaultEvent: AlertManagerAlert
map:
    credentialsInvalid:
      - alert: PersonalCalendarError  # The name of the condition in led-controller
        label: calendar               # Matches against alerts labeled calendar=john.doe@example.com
        value: john.doe@example.com
      - alert: WorkCalendarEvent
        label: calendar
        value: john.doe@work.com
```

