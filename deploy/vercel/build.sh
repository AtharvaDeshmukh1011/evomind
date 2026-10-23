set -e
rm -rf site
mkdir site
cp -r backend/evomind/api/static site/static
sed 's#<head>#<head>\n<script>window.EVOMIND_STATIC = true;</script>#' backend/evomind/api/static/index.html > site/index.html
