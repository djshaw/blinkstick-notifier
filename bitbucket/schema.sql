CREATE TABLE IF NOT EXISTS properties(
    name TEXT,
    value TEXT,

    PRIMARY KEY( name )
);

CREATE TABLE IF NOT EXISTS users(
    identifier TEXT,
    username TEXT,

    PRIMARY KEY( identifier )
);

