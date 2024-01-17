class Navbar:
    def render( self ):
        return """
            <nav class="navbar navbar-expand-lg navbar-light bg-light">
                <a class="navbar-brand" href="/">Blinkstick</a>
                <div class="collapse navbar-collapse" id="navbarSupportedContent">
                    <ul class="navbar-nav mr-auto">
                        <li class="nav-item active">
                            <a class="nav-link" href="/">Home</a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="/calendarListener">CalendarListener</a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="/outlookListener">OutlookListener</a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="/bitbucket">Bitbucket</a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="/webhook">Webhook</a>
                        </li>
                        <li class="nav-item dropdown">
                            <a class="nav-link dropdown-toggle" href="#" id="navbarDropdown" role="button" data-toggle="dropdown" aria-haspopup="true" aria-expanded="false">Diagnostics</a>
                            <div class="dropdown-menu" aria-labelledby="navbarDropdown">
                                <!-- TODO: use the current hostname to populate the links! -->
                                <a class="dropdown-item" href="http://blinkstick:9090/">Prometheus</a>
                                <a class="dropdown-item" href="http://blinkstick:9093/">AlertManager</a>
                                <a class="dropdown-item" href="/manualSet.html">ManualSet</a>
                            </div>
                        </li>
                    </ul>
                </div>
            </nav>
            """

