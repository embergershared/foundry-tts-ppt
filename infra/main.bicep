// Foundry resource for text to speech: a Foundry (AIServices) account with keys off and public
// network access, a project, a gpt-4o-mini-tts deployment, and the Cognitive Services User role
// for the person who runs `azd provision`. Azure Speech voices (HD, MAI-Voice) need no deployment.
targetScope = 'subscription'

@minLength(1)
@maxLength(32)
@description('azd environment name; used in resource names and the azd-env-name tag.')
param environmentName string

@minLength(1)
@description('Region of the resource group and the Foundry resource. It must offer the Speech HD voices and the TTS model: eastus2 does (checked 2026-11-10; swedencentral has no gpt-4o-mini-tts).')
@metadata({ azd: { type: 'location' } })
param location string

@description('Object ID of the user who gets the Cognitive Services User role (azd sets AZURE_PRINCIPAL_ID).')
param principalId string = ''

@allowed([
  'User'
  'ServicePrincipal'
])
@description('Type of principalId.')
param principalType string = 'User'

@description('Deploy the gpt-4o-mini-tts model (the "openai" engine). The Speech engine works without it.')
param deployTtsModel bool = true

@description('Model and version of the TTS deployment.')
param ttsModelName string = 'gpt-4o-mini-tts'
param ttsModelVersion string = '2025-12-15'

@description('Deployment SKU and capacity (in thousands of tokens per minute) of the TTS deployment.')
param ttsDeploymentSku string = 'GlobalStandard'
param ttsDeploymentCapacity int = 1

var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))
var tags = { 'azd-env-name': environmentName }
var foundryName = 'fdy-tts-${resourceToken}'
var projectName = 'proj-tts'
// Built-in role: Cognitive Services User (data actions on the Foundry resource, Speech and OpenAI).
var cognitiveServicesUserRoleId = 'a97b65f3-24c7-4388-baec-2e87135dc908'

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

module foundry 'foundry.bicep' = {
  name: 'foundry'
  scope: rg
  params: {
    name: foundryName
    projectName: projectName
    location: location
    tags: tags
    principalId: principalId
    principalType: principalType
    roleDefinitionId: cognitiveServicesUserRoleId
    deployTtsModel: deployTtsModel
    ttsModelName: ttsModelName
    ttsModelVersion: ttsModelVersion
    ttsDeploymentSku: ttsDeploymentSku
    ttsDeploymentCapacity: ttsDeploymentCapacity
  }
}

// Names and endpoints only: the resource has keys turned off and nothing secret is output.
output AZURE_RESOURCE_GROUP string = rg.name
output FOUNDRY_NAME string = foundry.outputs.name
output FOUNDRY_RESOURCE_ID string = foundry.outputs.id
output FOUNDRY_REGION string = location
output FOUNDRY_OPENAI_ENDPOINT string = foundry.outputs.openAiEndpoint
output FOUNDRY_TTS_DEPLOYMENT string = deployTtsModel ? foundry.outputs.ttsDeploymentName : ''
