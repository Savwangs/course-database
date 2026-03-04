# Push new image
gcloud builds submit --tag gcr.io/coursegenie-project/coursegenie:latest OpenAI_Chatbot_Integration

# Deploy image to GCP
gcloud run deploy coursegenie \
  --image gcr.io/coursegenie-project/coursegenie:latest \
  --region us-west2 \
  --platform managed