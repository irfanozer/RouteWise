targetScope = 'resourceGroup'

metadata name = 'RouteWise database migration job'
metadata description = 'A manually triggered Alembic job used before an application revision is deployed.'

param location string = resourceGroup().location

@minLength(3)
@maxLength(15)
param namePrefix string = 'routewise'

@minLength(2)
@maxLength(7)
param environmentName string = 'prod'

param containerAppsEnvironmentName string = 'cae-${toLower(namePrefix)}-${toLower(environmentName)}'

@minLength(1)
param backendImage string

@secure()
@minLength(1)
param databaseUrl string

@minLength(1)
param registryServer string = 'ghcr.io'

@minLength(1)
param registryUsername string

@secure()
@minLength(1)
param registryPassword string

param tags object = {}

var normalizedPrefix = toLower(namePrefix)
var normalizedEnvironment = toLower(environmentName)
var jobName = '${normalizedPrefix}-migrate-${normalizedEnvironment}'
var resourceTags = union({
  application: 'RouteWise'
  environment: normalizedEnvironment
  managedBy: 'Bicep'
  workload: 'database-migration'
}, tags)

resource containerAppsEnvironment 'Microsoft.App/managedEnvironments@2026-01-01' existing = {
  name: containerAppsEnvironmentName
}

resource migrationJob 'Microsoft.App/jobs@2025-07-01' = {
  name: jobName
  location: location
  tags: resourceTags
  properties: {
    configuration: {
      replicaRetryLimit: 1
      replicaTimeout: 600
      triggerType: 'Manual'
      manualTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
      }
      secrets: [
        {
          name: 'database-url'
          value: databaseUrl
        }
        {
          name: 'registry-password'
          value: registryPassword
        }
      ]
      registries: [
        {
          server: registryServer
          username: registryUsername
          passwordSecretRef: 'registry-password'
        }
      ]
    }
    environmentId: containerAppsEnvironment.id
    template: {
      containers: [
        {
          name: 'migration'
          image: backendImage
          command: [
            'alembic'
          ]
          args: [
            'upgrade'
            'head'
          ]
          env: [
            {
              name: 'ROUTEWISE_ENVIRONMENT'
              value: 'production-migration'
            }
            {
              name: 'ROUTEWISE_DATABASE_URL'
              secretRef: 'database-url'
            }
            {
              name: 'ROUTEWISE_AUTO_CREATE_SCHEMA'
              value: 'false'
            }
          ]
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
        }
      ]
    }
    workloadProfileName: 'Consumption'
  }
}

output migrationJobName string = migrationJob.name
