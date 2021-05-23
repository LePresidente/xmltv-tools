#TMDB xmltv enhancement

Description
This script will try update your xmltv guide with series posters and movie posters, also update your movie entries with updated descriptions,rating and category information. This will generate a new file called enhanced-xmltv.xml that you can use to import as into your iptv guide
posters will be saved localy into /output/Artwork (This is configurable see below)

Your media manager that will import this file should match the location below

Environment Variables used by the docker image below
REDIS_HOST,
These variables allow you to set the hostname or IP address of the REDIS host, respectively. Default is Localhost

REDIS_PORT,
This variable sets the port that Redis-cli will use , Default is 6379

REDIS_PASS
This variable sets the password that Redis, there is no default value

TMDB_API
This variable sets the TMDB_API code to use to connect to TMDB. There is no default value.

To Use with docker:
docker run -t --rm -v $(pwd)}:/output --env REDIS_HOST=<REDISHOST> --env TMDB_API=<TMDBAPI> lepresidente/xmltv-tools -o /output /output/xmltv.xml



