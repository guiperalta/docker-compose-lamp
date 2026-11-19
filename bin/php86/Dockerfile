FROM php:8.6-apache-bookworm

# Surpresses debconf complaints of trying to install apt packages interactively
# https://github.com/moby/moby/issues/4032#issuecomment-192327844
 
ARG DEBIAN_FRONTEND=noninteractive

# Update
RUN apt-get -y update --fix-missing && \
    apt-get upgrade -y && \
    apt-get --no-install-recommends install -y apt-utils && \
    rm -rf /var/lib/apt/lists/*


# Install useful tools and install important libaries
RUN apt-get -y update && \
    apt-get -y --no-install-recommends install wget \
dialog \
libsqlite3-dev \
libsqlite3-0 && \
    apt-get -y --no-install-recommends install default-mysql-client \
zlib1g-dev \
libzip-dev \
libicu-dev && \
    apt-get -y --no-install-recommends install --fix-missing apt-utils \
build-essential \
git \
curl \
libonig-dev && \ 
    apt-get install -y iputils-ping && \
    apt-get -y --no-install-recommends install --fix-missing libcurl4 \
libcurl4-openssl-dev \
zip \
openssl && \
    rm -rf /var/lib/apt/lists/* && \
    curl -sS https://getcomposer.org/installer | php -- --install-dir=/usr/local/bin --filename=composer

# Install xdebug
# PHP 8.6 image ships no pecl: build xdebug from source (default branch, newest)
RUN cd /usr/local/src && \
    git clone --depth 1 https://github.com/xdebug/xdebug && \
    cd xdebug && phpize && ./configure --enable-xdebug && make && make install && \
    cd .. && rm -rf xdebug && \
    docker-php-ext-enable xdebug && \
    mkdir /var/log/xdebug

# Install redis
#RUN pecl install redis-6.0.2 && \
#    docker-php-ext-enable redis

# Install imagick
RUN apt-get update && \
    apt-get -y --no-install-recommends install --fix-missing libmagickwand-dev && \
    rm -rf /var/lib/apt/lists/*

# Imagick Commit to install
# https://github.com/Imagick/imagick
ARG IMAGICK_COMMIT="master"

RUN cd /usr/local/src && \
    git clone https://github.com/Imagick/imagick && \
    cd imagick && \
    git checkout ${IMAGICK_COMMIT} && \
    phpize && \
    ./configure && \
    make && \
    make install && \
    cd .. && \
    rm -rf imagick && \
    docker-php-ext-enable imagick

# Other PHP8 Extensions

RUN docker-php-ext-install pdo_mysql && \
    docker-php-ext-install pdo_sqlite && \
    docker-php-ext-install bcmath && \
    docker-php-ext-install mysqli && \
    docker-php-ext-install curl && \
    docker-php-ext-install zip && \
    docker-php-ext-install -j$(nproc) intl && \
    docker-php-ext-install mbstring && \
    docker-php-ext-install gettext && \
    docker-php-ext-install calendar && \
    docker-php-ext-install exif


# Install Freetype 
RUN apt-get -y update && \
    apt-get --no-install-recommends install -y libfreetype6-dev \
libjpeg62-turbo-dev \
libpng-dev && \
    rm -rf /var/lib/apt/lists/* && \
    docker-php-ext-configure gd --enable-gd --with-freetype --with-jpeg && \
    docker-php-ext-install gd

RUN apt-get -y update && \
    apt-get install ghostscript vim -y

# Ensure an SSL directory exists and create logs folder
RUN mkdir -p /etc/apache2/ssl && \
    mkdir -p /var/www && \
    mkdir -p -m 777 /var/www/logs

# Enable SSL support
RUN a2enmod ssl && a2enmod rewrite

# Enable apache modules
RUN a2enmod rewrite headers

# Run Apache as the host user that owns the bind-mounted project folder.
# By default www-data is uid 33, so anything the host creates under the mount with
# mode 755 (upload folders, staged files) is read-only to PHP: uploads fail and
# temp files are never cleaned up. Mapping www-data onto the host uid/gid makes
# files written inside the container land with the right ownership instead.
# Override per machine with:
#   docker compose build --build-arg PUID=$(id -u) --build-arg PGID=$(id -g) webserver
ARG PUID=1000
ARG PGID=1000
RUN groupmod -o -g "${PGID}" www-data && \
    usermod -o -u "${PUID}" -g "${PGID}" www-data && \
    for d in /var/www /var/log/apache2 /var/lock/apache2 /var/run/apache2; do \
        [ -e "$d" ] && chown -R www-data:www-data "$d"; \
    done; \
    true

# Cleanup
RUN rm -rf /usr/src/*
