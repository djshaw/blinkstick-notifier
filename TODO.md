# TODO List

No meaning should be taken from the order of these items.

- [ ] Verify that ctrl-c is working
- [ ] Add test case to validate sent and received json messages match the schema
- [ ] Normalize container names from `CamleCase` to `kebab-case`
- [ ] Integrate markdown linting to verify links and images
- [ ] Verify git secrets hooks working correctly
- [ ] Write an endpoint that receves webhook call backs for google calendar event
      changes, then forward the messages via websocket to `calendarListener`
- [ ] Rename `calendarListener` to `google-listener`
- [ ] Normalize Listener to Sensor
- [ ] Add new email monitoring
- [ ] Poll less frequently.  Maybe once every 10 minutes. (Configurable, of course)
- [ ] Tone down `node_exporter`/`cadvisor` so it doesn't take up ass much cpu time
- [ ] Update `promtail-config.yaml` to identify info, warning, error, fatal (right
      now it only identifies debug)
- [ ] The webui is klunky.  It could be made much more user friendly
- [ ] vue3 web ui xor use template files
- [ ] Python modules aren't actually semantic python modules.  It might be easier
      to compile them down to eggs.
- [ ] Unit, integration, functional tests for everything!
- [ ] better anonyimization of uuids in sample files: generate new random values,
      or set to all 0s
- [ ] Create unique logging channels for each external api
- [ ] Integrate coverage-gutters into setup:

Install `coverage` with:
```Shell
pip3 install coverage
```

Run a unit test with:
```Shell
python -m coverage run -m unittest ledController/test/unit/ledController_test.py
```

Convert the coverage data to `xml`:
```Shell
coverage xml
```

If the coverage-gutters extension is installed, coverage data should automatically be shown in
vscode
