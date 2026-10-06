window.addEventListener('load', () => {
  window.ui = SwaggerUIBundle({
    url: '/api/v1/openapi.json', dom_id: '#swagger-ui', deepLinking: true, tryItOutEnabled: true,
    displayRequestDuration: true, docExpansion: 'list', defaultModelsExpandDepth: 0,
  });
});
