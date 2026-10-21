pipeline {
    agent any

    environment {
        IMAGE = 'ahmadyousaf56/prod-backend'
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
                sh 'ls -la'
            }
        }
        stage('Build') {
            steps {
                sh 'docker compose build'
            }
        }
        stage('Test') {
            steps {
                sh 'docker compose config -q'
                sh 'helm lint helm/prod-stack'
            }
        }
        stage('Push') {
            steps {
                sh 'docker build -t $IMAGE:$BUILD_NUMBER ./backend'
                withCredentials([usernamePassword(credentialsId: 'dockerhub-creds', usernameVariable: 'DH_USER', passwordVariable: 'DH_PASS')]) {
                    sh 'echo "$DH_PASS" | docker login -u "$DH_USER" --password-stdin'
                    sh 'docker push $IMAGE:$BUILD_NUMBER'
                    sh 'docker logout'
                }
            }
        }
    }
}
