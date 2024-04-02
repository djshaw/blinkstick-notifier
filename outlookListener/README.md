# outlook-listener

The `outlook-listener` sensor polls Microsoft's graph api endpoint for a [list of calendars](https://learn.microsoft.com/en-us/graph/api/user-list-calendarview?view=graph-rest-1.0&tabs=http).

## Creating an App for Client Credentials

App credentials are required to use the graph endpoint.  To create credentials, go to
portal.azure.com.  Go to "App registrations" and click "New registration".  Provide a name of your
choice.  The `Supported account types` can be constrained to `Accounts in this organizational
directory only`, the default option.

For the simplest setup, the Redirect URI should be `http://localhost:8080/outlookListener`.

The Application (client) ID needs to be put in `credentials.yaml`'s `client_id` value.

The App needs the permission to query a users calendar.  In "API permissions", click "Add a
permission", then click on "Microsoft Graph", and "Delegated permissions".  Two permissions are
required `Calendars.Read` and `User.Read`.

The Redirect URI specified needs to be specified in `credentials.yaml`'s `redirect_uri`.

## Creating a Client Secret And Creating `credentials.yaml`

Generate a Client secret by going to "Certificates & secrets", then "Client secrets", click "New
client secret".  Provide a description for the secret and specify when the secret expires.  The
secret will expire at most 2 years from the day the secret is created.  

The Client secret `Value` needs to be put in `credentials.yaml`'s `client_secret` value.

When the client secret expires, the old secret can be deleted and a new one generated.

## Sample `credentials.yaml` File

A `credentials.yaml` file looks like:

```yaml
client_id: "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
client_secret: "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
redirect_uri: "http://localhost:8080/outlookListener"
authority: "https://login.microsoftonline.com/organizations/"
scope: ["Calendars.Read"]
```
