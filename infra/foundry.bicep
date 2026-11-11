// The Foundry resource, its project, the TTS model deployment and the user's role assignment.

param name string
param projectName string
param location string
param tags object
param principalId string
param principalType string
param roleDefinitionId string
param deployTtsModel bool
param ttsModelName string
param ttsModelVersion string
param ttsDeploymentSku string
param ttsDeploymentCapacity int

resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: name
  location: location
  tags: tags
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    allowProjectManagement: true
    // The custom subdomain gives the resource its own endpoints, needed for Entra ID sign-in.
    customSubDomainName: name
    // Keys off: callers sign in with Microsoft Entra ID only.
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: foundry
  name: projectName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {}
}

resource ttsDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = if (deployTtsModel) {
  parent: foundry
  name: ttsModelName
  // One change at a time on the account: a deployment created alongside the project can fail.
  dependsOn: [
    project
  ]
  sku: {
    name: ttsDeploymentSku
    capacity: ttsDeploymentCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: ttsModelName
      version: ttsModelVersion
    }
  }
}

resource userRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId)) {
  name: guid(foundry.id, principalId, roleDefinitionId)
  scope: foundry
  properties: {
    principalId: principalId
    principalType: principalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleDefinitionId)
  }
}

output name string = foundry.name
output id string = foundry.id
output openAiEndpoint string = 'https://${name}.openai.azure.com'
output ttsDeploymentName string = deployTtsModel ? ttsModelName : ''
output projectName string = project.name
