#!/bin/bash

echo "🔍 Checking if Docker is installed..."
if ! command -v docker &> /dev/null
then
    echo "🚨 Docker is not installed. Installing Docker..."
    brew install --cask docker
    echo "✅ Docker installed. Please start Docker Desktop and re-run this script."
    exit 1
else
    echo "✅ Docker is already installed!"
fi

# Create a Docker network for Elasticsearch and Kibana
echo "🔧 Creating a Docker network 'elastic-net'..."
docker network create elastic || echo "⚠️ Network already exists!"

# Start Elasticsearch container
echo "🚀 Starting Elasticsearch..."
docker run --name elasticsearch --net elastic -p 9200:9200 -it -m 1GB \
  -e "discovery.type=single-node" \
  -e "xpack.security.enabled=false" \
  -e "xpack.security.http.ssl.enabled=false" \
  -e "ELASTIC_PASSWORD=password" \
  docker.elastic.co/elasticsearch/elasticsearch:8.17.2

# Wait for Elasticsearch to start
echo "⏳ Waiting for Elasticsearch to start..."
sleep 15

# Start Kibana container
echo "🚀 Starting Kibana..."
docker run --name kibana --net elastic -p 5601:5601 \
  -e "ELASTICSEARCH_HOSTS=http://elasticsearch:9200" \
  docker.elastic.co/kibana/kibana:8.17.2

# Wait for Kibana to start
echo "⏳ Waiting for Kibana to start..."
sleep 10

docker run --name apm-server --net elastic -p 8200:8200 \
  -e "output.elasticsearch.hosts=[\"http://elasticsearch:9200\"]" \
  -e "output.elasticsearch.username=elastic" \
  -e "output.elasticsearch.password=password" \
  -e "apm-server.secret_token=" \
  -e "apm-server.auth.anonymous.enabled=true" \
  docker.elastic.co/apm/apm-server:8.17.2

# Display status
echo "🎉 Installation Complete!"
echo "🌐 Access Kibana at: http://localhost:5601"
echo "📡 Elasticsearch API: http://localhost:9200"
