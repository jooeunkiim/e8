import torchvision.transforms as transforms
from torchvision.datasets import ImageFolder
import torch
from torch.utils.data import DataLoader
import torchvision.models as models
import torchvision
import numpy as np
import matplotlib.pyplot as plt
import torch.nn as nn 
import argparse

parser = argparse.ArgumentParser(description="train efficientnet-b0")
parser.add_argument("--model", default="eff_net.pt", type=str, help="model name to load from")
args = parser.parse_args()

transforms = transforms.Compose([
    transforms.ToTensor(),
    transforms.Resize((224, 224)) # H, W
])

test_dir  = '../dataset/val'
testset = ImageFolder(root=test_dir, transform=transforms, target_transform=None)
testloader = DataLoader(testset, batch_size=1, shuffle=True, pin_memory=True, num_workers=4)

PATH = args.model
dataiter = iter(testloader) 
images, labels = dataiter.next() # 실험용 데이터와 결과 출력 
def imsave(img):
    npimg = img.numpy()
    plt.figure(1, figsize=(12, 12))
    plt.imshow(np.transpose(npimg, (1,2,0)))
    plt.savefig("evaluate.png", dpi=600)
    plt.clf()
imsave(torchvision.utils.make_grid(images)) 
print('GroundTruth: ', ' '.join('%5s' % testset.classes[label] for label in labels)) # 학습한 모델로 예측값 뽑아보기 
def build_net(num_classes):
    net = models.efficientnet_b0(pretrained=True)
    num_ftrs = net.fc.in_features
    net.fc = nn.Linear(num_ftrs, num_classes)
    return net

net = build_net(len(testset.classes))
net.load_state_dict(torch.load(PATH)) 
outputs = net(images)
_, predicted = torch.max(outputs, 1) 
print('Predicted: ', ' '.join('%5s' %  testset.classes[predict] for predict in predicted))


correct = 0 
total = 0 
f1 = 0
from sklearn.metrics import f1_score
with torch.no_grad(): 
    for data in testloader: 
        images, labels = data 
        outputs = net(images) 
        _, predicted = torch.max(outputs.data, 1) 
        f1 += f1_score(labels.numpy(), predicted.numpy())
        total += labels.size(0) 
        correct += (predicted == labels).sum().item() 
        print('Accuracy of the network on the test images: %d %%' % ( 100 * correct / total))
        print("Average F1 score : %f %%" % (f1 / total))